import itertools
import port.api.props as props
from port.api.commands import CommandSystemDonate, CommandUIRender

import pandas as pd
import zipfile
import json
import datetime
import pytz
import fnmatch
from collections import defaultdict, namedtuple
from contextlib import suppress

##########################
# Instagram file processing #
##########################

filter_start = datetime.datetime(1990, 1, 1)
filter_end = datetime.datetime(2025, 1, 1)

datetime_format = "%Y-%m-%d %H:%M:%S"


def parse_datetime(value):
    utc_datetime = datetime.datetime.fromtimestamp(value, tz=datetime.timezone.utc)
    uk_timezone = pytz.timezone("Europe/London")
    return uk_timezone.normalize(utc_datetime.astimezone(uk_timezone))


def get_in(data_dict, *key_path):
    for k in key_path:
        data_dict = data_dict.get(k, None)
        if data_dict is None:
            return None
    return data_dict


def get_list(data_dict, *key_path):
    result = get_in(data_dict, *key_path)
    if result is None:
        return []
    return result


def get_dict(data_dict, *key_path):
    result = get_in(data_dict, *key_path)
    if result is None:
        return {}
    return result


def get_string(data_dict, *key_path):
    result = get_in(data_dict, *key_path)
    if result is None:
        return ""
    return result


def cast_number(data_dict, *key_path):
    value = get_in(data_dict, *key_path)
    if value is None or value == "None":
        return 0
    return value


def get_activity_video_browsing_list_data(data):
    return get_list(data, "Activity", "Video Browsing History", "VideoList")


def get_comment_list_data(data):
    return get_in(data, "Comment", "Comments", "CommentsList")


def filter_timestamps(timestamps):
    for timestamp in timestamps:
        if timestamp < filter_start or timestamp > filter_end:
            continue
        yield timestamp


def get_count_by_date_key(timestamps, key_func):
    """Returns a dict of the form (key, count)

    The key is determined by the key_func, which takes a datetime object and
    returns an object suitable for sorting and usage as a dictionary key.

    The returned list is sorted by key.
    """
    item_count = defaultdict(int)
    for timestamp in timestamps:
        item_count[key_func(timestamp)] += 1
    return sorted(item_count.items())


def get_all_first(items):
    return (i[0] for i in items)


def hourly_key(date):
    return date.replace(minute=0, second=0, microsecond=0)


def daily_key(date):
    return date.date()


# =====================
def glob(zipfile, pattern):
    return fnmatch.filter(zipfile.namelist(), pattern)


def glob_json(zipfile, pattern):
    for name in glob(zipfile, pattern):
        with zipfile.open(name) as f:
            yield json.load(f)


# =====================


def get_sessions(timestamps):
    """Returns a list of tuples of the form (start, end, duration)

    The start and end are datetime objects, and the duration is a timedelta
    object.
    """
    timestamps = list(sorted(timestamps))
    if len(timestamps) == 0:
        return []
    if len(timestamps) == 1:
        return [(timestamps[0], timestamps[0], datetime.timedelta(0))]

    sessions = []
    start = timestamps[0]
    end = timestamps[0]
    for prev, cur in zip(timestamps, timestamps[1:]):
        if cur - prev > datetime.timedelta(minutes=5):
            sessions.append((start, end, end - start))
            start = cur
        end = cur
    sessions.append((start, end, end - start))
    return sessions


def filtered_count(data, *key_path):
    items = get_list(data, *key_path)
    filtered_items = get_date_filtered_items(items)
    return len(list(filtered_items))


def get_chat_history(data):
    return get_dict(data, "Direct Messages", "Chat History", "ChatHistory")


def flatten_chat_history(history):
    return itertools.chain(*history.values())


def filter_by_key(items, key, value):
    return filter(lambda item: item[key] == value, items)


def exclude_by_key(items, key, value):
    """
    Return a filtered list where items that match key & value are excluded.
    """
    return filter(lambda item: item[key] != value, items)


def map_to_timeslot(series):
    return series.map(lambda hour: f"{hour}-{hour+1}")


def count_items(zipfile, pattern, key):
    count = 0
    for data in glob_json(zipfile, pattern):
        # Some files have dictionary, others a list of dictionaries. Normalize
        # this to always a list so the rest of the code works regardless.
        if isinstance(data, dict):
            data = [data]
        for item in data:
            count += len(item[key])
    return count


def count_posts(zipfile):
    return sum(len(data) for data in glob_json(zipfile, "*/content/posts_*.json"))


def count_messages(zipfile):
    counts = {"sent": 0, "received": 0}
    for data in glob_json(zipfile, "*/messages/inbox/**/message_*.json"):
        donating_user = get_donating_user(data)
        for message in data["messages"]:
            key = "sent" if message["sender_name"] == donating_user else "received"
            counts[key] += 1
    return counts


def get_donating_user(data):
    participants = data["participants"]
    return participants[len(participants) - 1]["name"]


def extract_summary_data(zipfile):
    message_counts = count_messages(zipfile)
    summary_data = {
        "Description": [
            "Followers",
            "Following",
            "Posts",
            "Comments posted",
            "Videos watched",
            "Posts viewed",
            "Messages sent",
            "Messages received",
            "Ads viewed",
        ],
        "Number": [
            count_items(
                zipfile,
                "*/followers_and_following/followers_*.json",
                "string_list_data",
            ),
            count_items(
                zipfile,
                "*/followers_and_following/following.json",
                "relationships_following",
            ),
            count_posts(zipfile),
            count_items(
                zipfile, "*/comments/post_comments.json", "comments_media_comments"
            ),
            count_items(
                zipfile,
                "*/ads_and_topics/videos_watched.json",
                "impressions_history_videos_watched",
            ),
            count_items(
                zipfile,
                "*/ads_and_topics/posts_viewed.json",
                "impressions_history_posts_seen",
            ),
            message_counts["sent"],
            message_counts["received"],
            count_items(
                zipfile,
                "*/ads_and_topics/ads_viewed.json",
                "impressions_history_ads_seen",
            ),
        ],
    }

    visualizations = []

    return ExtractionResult(
        "instagram_summary",
        props.Translatable(
            {"en": "Summary information", "nl": "Samenvatting gegevens"}
        ),
        pd.DataFrame(summary_data),
        None,
        visualizations,
    )


def extract_direct_message_activity(zipfile):
    counter = itertools.count()
    person_ids = defaultdict(lambda: next(counter))
    sender_ids = []
    timestamps = []
    for data in glob_json(zipfile, "*/messages/inbox/**/message_*.json"):
        # Ensure the donating user is the first to get an ID
        donating_user = get_donating_user(data)
        person_ids[donating_user]
        for message in data["messages"]:
            sender_ids.append(person_ids[message["sender_name"]])
            timestamps.append(parse_datetime(message["timestamp_ms"] / 1000))
    df = pd.DataFrame({"Anonymous ID": sender_ids, "Sent": timestamps})
    df["Sent"] = pd.to_datetime(df["Sent"]).dt.strftime("%Y-%m-%d %H:%M")

    description = props.Translatable(
        {
            "en": "This table shows the times of the messages sent or received by you. The message content is not included, and names have been anonymized.",
        }
    )

    visualizations = [
        dict(
            title={
                "en": "Direct message activity over time",
                "nl": "Direct message activiteit in de loop van de tijd",
            },
            type="area",
            group=dict(column="Sent", dateFormat="auto"),
            values=[
                dict(
                    label="Messages",
                    column="Anonymous ID",
                    aggregate="count",
                    addZeroes=True,
                )
            ],
        ),
        dict(
            title={
                "en": "Direct message activity per hour of the day",
                "nl": "Direct message activiteit per uur van de dag",
            },
            type="bar",
            group=dict(column="Sent", dateFormat="hour_cycle"),
            values=[
                dict(
                    label="Messages",
                    column="Anonymous ID",
                    aggregate="count",
                    addZeroes=True,
                )
            ],
        ),
    ]

    return ExtractionResult(
        "instagram_direct_message_activity",
        props.Translatable(
            {"en": "Direct message activity", "nl": "Bericht activiteit"}
        ),
        df,
        description,
        visualizations,
    )


## REMOVED ON REQUEST BY CAMBRIDGE (see notion)
def extract_comment_activity(zipfile):
    timestamps = []
    for data in glob_json(zipfile, "*/comments/post_comments.json"):
        for item in data["comments_media_comments"]:
            timestamps.append(
                parse_datetime(item["string_map_data"]["Time"]["timestamp"])
            )
    df = pd.DataFrame({"Posted": timestamps})
    df = df.sort_values("Posted")
    df["Posted"] = pd.to_datetime(df["Posted"]).dt.strftime("%Y-%m-%d %H:%M")

    visualizations = [
        dict(
            title={
                "en": "Comment activity over time",
                "nl": "Comment activiteit in de loop van de tijd",
            },
            type="area",
            group=dict(column="Posted", dateFormat="auto"),
            values=[
                dict(
                    label="Comment activity",
                    aggregate="count",
                    addZeroes=True,
                )
            ],
        )
    ]

    return ExtractionResult(
        "instagram_comment_activity",
        props.Translatable({"en": "Comment activity", "nl": "Commentaar activiteit"}),
        df,
        None,
        visualizations,
    )


# CURRENTLY NOT USED:
# CAMBRIDGE ASKED TO REMOVE THE 'POSTS LIKED' (ON NOTION)
def extract_posts_liked(zipfile):
    timestamps = []
    for data in glob_json(zipfile, "*/likes/liked_posts.json"):
        for item in data["likes_media_likes"]:
            info = item["string_list_data"][0]
            timestamps.append(parse_datetime(info["timestamp"]))
    df = pd.DataFrame({"Liked": timestamps})
    df["Liked"] = pd.to_datetime(df["Liked"]).dt.strftime("%Y-%m-%d %H:%M")
    df = df.sort_values("Liked")
    visualizations = [
        dict(
            title={
                "en": "Posts liked per day of the week",
                "nl": "Posts geliked per dag van de week",
            },
            type="bar",
            group=dict(column="Liked", dateFormat="day_cycle"),
            values=[
                dict(
                    label="likes",
                    column="Liked",
                    aggregate="count",
                    addZeroes=True,
                )
            ],
        ),
        dict(
            title={
                "en": "Posts liked per hour of the day",
                "nl": "Posts geliked per uur van de dag",
            },
            type="bar",
            group=dict(column="Liked", dateFormat="hour_cycle"),
            values=[
                dict(
                    label="likes",
                    column="Liked",
                    aggregate="count",
                    addZeroes=True,
                )
            ],
        ),
    ]
    return ExtractionResult(
        "instagram_posts_liked",
        props.Translatable({"en": "Posts Liked", "nl": "Geliked"}),
        df,
        None,
        visualizations,
    )


def flatten_media(items):
    for item in items:
        yield from item["media"]


def get_creation_timestamps(items):
    for item in items:
        yield parse_datetime(item["creation_timestamp"])


def get_media_creation_timestamps(items):
    return get_creation_timestamps(flatten_media(items))


def get_content_posts_timestamps(zipfile):
    for data in glob_json(zipfile, "*/content/posts_*.json"):
        yield from get_media_creation_timestamps(data)


def get_media_timestamps(zipfile, pattern, key):
    for data in glob_json(zipfile, pattern):
        yield from get_media_creation_timestamps(data[key])


def df_from_timestamps(timestamps, column):
    df = pd.DataFrame({"timestamps": timestamps})
    counts = df.groupby(lambda x: hourly_key(df["timestamps"][x])).size()

    df = counts.reset_index()
    df.columns = ["timestamp", column]
    return df


def stories_timestamps(zipfile):
    for data in glob_json(zipfile, "*/content/stories.json"):
        for item in data["ig_stories"]:
            yield parse_datetime(item["creation_timestamp"])


def df_from_timestamp_columns(a, b):
    data_frames = [
        df_from_timestamps(timestamps, column) for timestamps, column in [a, b]
    ]

    df = pd.merge(
        data_frames[0],
        data_frames[1],
        left_on="timestamp",
        right_on="timestamp",
        how="outer",
    ).sort_index()
    df["Date"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d %H:00:00")
    df["Timeslot"] = map_to_timeslot(pd.to_datetime(df["timestamp"]).dt.hour)
    df = df.reset_index(drop=True)
    df = (
        df.reindex(columns=["Date", "Timeslot", a[1], b[1]])
        .reset_index(drop=True)
        .fillna(0)
    )
    df[a[1]] = df[a[1]].astype(int)
    df[b[1]] = df[b[1]].astype(int)
    return df


def get_video_posts_timestamps(zipfile):
    return itertools.chain(
        get_content_posts_timestamps(zipfile),
        get_media_timestamps(zipfile, "*/content/igtv_videos.json", "ig_igtv_media"),
        get_media_timestamps(zipfile, "*/content/reels.json", "ig_reels_media"),
    )


def extract_video_posts(zipfile):
    video_timestamps = get_video_posts_timestamps(zipfile)
    df = df_from_timestamp_columns(
        (video_timestamps, "Videos"), (stories_timestamps(zipfile), "Stories")
    )

    description = props.Translatable(
        {
            "en": "This table shows how many times you have posted content in either your feed or your story. For anonymization purposes, the exact time of the post is not shown, but grouped by the hour.",
        }
    )

    visualizations = [
        dict(
            title={
                "en": "Videos and stories over time",
                "nl": "Video's en stories in de loop van de tijd",
            },
            type="line",
            group=dict(column="Date", dateFormat="auto"),
            values=[
                dict(
                    label="Videos",
                    column="Videos",
                    aggregate="sum",
                    addZeroes=True,
                ),
                dict(
                    label="Stories",
                    column="Stories",
                    aggregate="sum",
                    addZeroes=True,
                ),
            ],
        ),
        dict(
            title={
                "en": "Videos and stories per hour of the day",
                "nl": "Video's en stories per uur van de dag",
            },
            type="bar",
            group=dict(column="Date", label="Hour", dateFormat="hour_cycle"),
            values=[
                dict(
                    label="Videos",
                    column="Videos",
                    aggregate="sum",
                    addZeroes=True,
                ),
                dict(
                    label="Stories",
                    column="Stories",
                    aggregate="sum",
                    addZeroes=True,
                ),
            ],
        ),
    ]
    return ExtractionResult(
        "instagram_video_posts",
        props.Translatable({"en": "Posts", "nl": "Posts"}),
        df,
        description,
        visualizations,
    )


def get_post_comments_timestamps(zipfile):
    return get_string_map_timestamps(
        zipfile, "*/comments/post_comments.json", "comments_media_comments"
    )


def get_string_list_timestamps(zipfile, pattern, key):
    for data in glob_json(zipfile, pattern):
        for item in data[key]:
            yield parse_datetime(item["string_list_data"][0]["timestamp"])


def get_string_map_timestamps(zipfile, pattern, key):
    for data in glob_json(zipfile, pattern):
        for item in data[key]:
            yield parse_datetime(item["string_map_data"]["Time"]["timestamp"])


def get_likes_timestamps(zipfile):
    return itertools.chain(
        get_string_list_timestamps(
            zipfile, "*/likes/liked_comments.json", "likes_comment_likes"
        ),
        get_string_list_timestamps(
            zipfile, "*/likes/liked_posts.json", "likes_media_likes"
        ),
    )


def extract_comments_and_likes(zipfile):
    comment_timestamps = get_post_comments_timestamps(zipfile)
    likes_timestamps = get_likes_timestamps(zipfile)
    df = df_from_timestamp_columns(
        (comment_timestamps, "Comments"), (likes_timestamps, "Likes")
    )

    description = props.Translatable(
        {
            "en": "This table shows how many times you have liked or commented content on Instagram.",
        }
    )

    visualizations = [
        dict(
            title={
                "en": "Comments and likes per month",
                "nl": "Comments en likes per maand",
            },
            type="line",
            group=dict(column="Date", label="Month", dateFormat="month"),
            values=[
                dict(
                    label="Comments",
                    column="Comments",
                    aggregate="sum",
                    addZeroes=True,
                ),
                dict(
                    label="Likes",
                    column="Likes",
                    aggregate="sum",
                    addZeroes=True,
                ),
            ],
        ),
        dict(
            title={
                "en": "Comments and likes per hour of the day",
                "nl": "Comments en likes per uur van de dag",
            },
            type="bar",
            group=dict(column="Date", label="Hour", dateFormat="hour_cycle"),
            values=[
                dict(
                    label="Comments",
                    column="Comments",
                    aggregate="sum",
                    addZeroes=True,
                ),
                dict(
                    label="Likes",
                    column="Likes",
                    aggregate="sum",
                    addZeroes=True,
                ),
            ],
        ),
    ]

    return ExtractionResult(
        "instagram_comments_and_likes",
        props.Translatable({"en": "Comments and likes", "nl": "Comments en likes"}),
        df,
        description,
        visualizations,
    )


def extract_viewed(zipfile):
    df = df_from_timestamp_columns(
        (
            get_string_map_timestamps(
                zipfile,
                "*/ads_and_topics/videos_watched.json",
                "impressions_history_videos_watched",
            ),
            "Videos",
        ),
        (
            get_string_map_timestamps(
                zipfile,
                "*/ads_and_topics/posts_viewed.json",
                "impressions_history_posts_seen",
            ),
            "Posts",
        ),
    )

    description = props.Translatable(
        {
            "en": "This table shows the number of videos and posts that you viewed over time.",
        }
    )

    visualizations = [
        dict(
            title={
                "en": "Number of videos and posts viewed over time",
                "nl": "Aantal video's en posts bekeken in de loop van de tijd",
            },
            type="line",
            group=dict(column="Date", label="Date", dateFormat="auto"),
            values=[
                dict(
                    label="Videos",
                    column="Videos",
                    aggregate="sum",
                    addZeroes=True,
                ),
                dict(
                    label="Posts",
                    column="Posts",
                    aggregate="sum",
                    addZeroes=True,
                ),
            ],
        ),
        dict(
            title={
                "en": "Videos and posts viewed per hour of the day",
                "nl": "Video's en posts bekeken per uur van de dag",
            },
            type="bar",
            group=dict(column="Date", label="Hour", dateFormat="hour_cycle"),
            values=[
                dict(
                    label="Videos",
                    column="Videos",
                    aggregate="sum",
                    addZeroes=True,
                ),
                dict(
                    label="Posts",
                    column="Posts",
                    aggregate="sum",
                    addZeroes=True,
                ),
            ],
        ),
    ]

    return ExtractionResult(
        "instagram_viewed",
        props.Translatable({"en": "Viewed", "nl": "Viewed"}),
        df,
        description,
        visualizations,
    )


def extract_session_info(zipfile):
    timestamps = list(
        itertools.chain(
            list(get_video_posts_timestamps(zipfile)),
            list(stories_timestamps(zipfile)),
            list(get_post_comments_timestamps(zipfile)),
            list(get_likes_timestamps(zipfile)),
        )
    )
    sessions = get_sessions(timestamps)
    df = pd.DataFrame(sessions, columns=["Start", "End", "Duration"])
    df["Start"] = pd.to_datetime(df["Start"]).dt.strftime("%Y-%m-%d %H:%M")
    df["Duration (in minutes)"] = (
        pd.to_timedelta(df["Duration"]).dt.total_seconds() / 60
    ).round(2)
    df = df.drop("End", axis=1)
    df = df.drop("Duration", axis=1)

    description = props.Translatable(
        {
            "en": "This table shows the number of minutes you spent on Instagram over time.",
        }
    )

    visualizations = [
        dict(
            title={
                "en": "Number of minutes spent on Instagram over time",
                "nl": "Aantal minuten besteed aan Instagram in de loop van de tijd",
            },
            type="area",
            group=dict(column="Start", dateFormat="auto"),
            values=[
                dict(
                    label="Minutes",
                    column="Duration (in minutes)",
                    aggregate="sum",
                    addZeroes=True,
                )
            ],
        )
    ]

    return ExtractionResult(
        "instagram_session_info",
        props.Translatable({"en": "Session information", "nl": "Sessie informatie"}),
        df,
        description,
        visualizations,
    )


def extract_data(path):
    extractors = [
        extract_summary_data,
        extract_video_posts,
        extract_comments_and_likes,
        extract_viewed,
        extract_session_info,
        extract_direct_message_activity,
        # extract_comment_activity,
        # extract_posts_liked,
    ]

    zfile = zipfile.ZipFile(path)

    return [extractor(zfile) for extractor in extractors]


######################
# Data donation flow #
######################


ExtractionResult = namedtuple(
    "ExtractionResult", ["id", "title", "data_frame", "description", "visualizations"]
)


class SkipToNextStep(Exception):
    pass


class DataDonationProcessor:
    def __init__(self, platform, mime_types, extractor, session_id):
        self.platform = platform
        self.mime_types = mime_types
        self.extractor = extractor
        self.session_id = session_id
        self.progress = 0
        self.meta_data = []

    def process(self):
        with suppress(SkipToNextStep):
            while True:
                file_result = yield from self.prompt_file()

                self.log(f"extracting file")
                try:
                    extraction_result = self.extract_data(file_result.value)
                except (IOError, zipfile.BadZipFile):
                    self.log(f"prompt confirmation to retry file selection")
                    try_again = yield from self.prompt_retry()
                    if try_again:
                        continue
                    return
                else:
                    if extraction_result is None:
                        try_again = yield from self.prompt_retry()
                        if try_again:
                            continue
                        else:
                            return
                    self.log(f"extraction successful, go to consent form")
                    yield from self.prompt_consent(extraction_result)

    def prompt_retry(self):
        retry_result = yield render_donation_page(
            self.platform, retry_confirmation(self.platform), self.progress
        )
        return retry_result.__type__ == "PayloadTrue"

    def prompt_file(self):
        description = props.Translatable(
            {
                "en": f"Click 'Choose file' to choose the file that you received from Instagram. If you click 'Continue', the data that is required for research is extracted from your file. This may take a while, thank you for your patience.",
                "nl": f"Klik op ‘Kies bestand’ om het bestand dat u ontvangen hebt van Instagram te kiezen. Als u op 'Verder' klikt worden de gegevens die nodig zijn voor het onderzoek uit uw bestand gehaald. Dit kan soms even duren. Een moment geduld a.u.b.",
            }
        )
        prompt_file = props.PropsUIPromptFileInput(description, self.mime_types)
        file_result = yield render_donation_page(
            self.platform, prompt_file, self.progress
        )
        if file_result.__type__ != "PayloadString":
            self.log(f"skip to next step")
            raise SkipToNextStep()
        return file_result

    def log(self, message):
        self.meta_data.append(("debug", f"{self.platform}: {message}"))

    def extract_data(self, file):
        return self.extractor(file)

    def prompt_consent(self, data):
        log_title = props.Translatable({"en": "Log messages", "nl": "Log berichten"})

        tables = [
            props.PropsUIPromptConsentFormTable(
                table.id,
                table.title,
                table.data_frame,
                table.description,
                table.visualizations,
            )
            for table in data
        ]
        meta_frame = pd.DataFrame(self.meta_data, columns=["type", "message"])
        meta_table = props.PropsUIPromptConsentFormTable(
            "log_messages", log_title, meta_frame
        )
        description = props.Translatable(
            {
                "en": """Decide whether you would like to donate the data below. Carefully check the data and adjust as required. Your donation will contibute to the reasearch project that was explained at the start of the project. Thank you in advance.
                    If you DO NOT want to donate any of the information in the table below, you can select the row and delete it from your data donation in the table below""",
            }
        )

        self.log(f"prompt consent")
        consent_result = yield render_donation_page(
            self.platform,
            props.PropsUIPromptConsentForm(tables, [meta_table], description),
            self.progress,
        )

        if consent_result.__type__ == "PayloadJSON":
            self.log(f"donate consent data")
            yield donate(f"{self.sessionId}-{self.platform}", consent_result.value)


class DataDonation:
    def __init__(self, platform, mime_types, extractor):
        self.platform = platform
        self.mime_types = mime_types
        self.extractor = extractor

    def __call__(self, session_id):
        processor = DataDonationProcessor(
            self.platform, self.mime_types, self.extractor, session_id
        )
        yield from processor.process()


data_donation = DataDonation("Instagram", "application/zip", extract_data)


def process(session_id):
    yield donate(f"{session_id}-tracking", '[{ "message": "user entered script" }]')
    yield from data_donation(session_id)


def render_donation_page(platform, body, progress):
    header = props.PropsUIHeader(props.Translatable({"en": platform, "nl": platform}))
    footer = props.PropsUIFooter(progress)
    page = props.PropsUIPageDonation(platform, header, body, footer)
    return CommandUIRender(page)


def retry_confirmation(platform):
    text = props.Translatable(
        {
            "en": f"Unfortunately, we cannot process your data. Please make sure that you selected a zip file, and JSON as a file format when downloading your data from Instagram.",
            "nl": f"Helaas, kunnen we uw {platform} bestand niet verwerken. Weet u zeker dat u het juiste bestand heeft gekozen? Ga dan verder. Probeer opnieuw als u een ander bestand wilt kiezen.",
        }
    )
    ok = props.Translatable({"en": "Try again", "nl": "Probeer opnieuw"})
    cancel = props.Translatable({"en": "Continue", "nl": "Verder"})
    return props.PropsUIPromptConfirm(text, ok, cancel)


def prompt_consent(id, data, meta_data):
    table_title = props.Translatable(
        {"en": "Zip file contents", "nl": "Inhoud zip bestand"}
    )

    log_title = props.Translatable({"en": "Log messages", "nl": "Log berichten"})

    data_frame = pd.DataFrame(data, columns=["filename", "compressed size", "size"])
    table = props.PropsUIPromptConsentFormTable("zip_content", table_title, data_frame)
    meta_frame = pd.DataFrame(meta_data, columns=["type", "message"])
    meta_table = props.PropsUIPromptConsentFormTable(
        "log_messages", log_title, meta_frame
    )

    return props.PropsUIPromptConsentForm([table], [meta_table])


def donate(key, json_string):
    return CommandSystemDonate(key, json_string)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        print(extract_data(sys.argv[1]))
    else:
        print("please provide a zip file as argument")
