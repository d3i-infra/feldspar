import { assert, Weak } from "../../../../helpers"
import {
  PropsUITable,
  PropsUITableBody,
  PropsUITableHead,
  PropsUITableRow,
  TableWithContext,
  TableContext,
} from "../../../../types/elements"
import { PropsUIPromptConsentForm, PropsUIPromptConsentFormTable } from "../../../../types/prompts"
import { LabelButton, PrimaryButton } from "../elements/button"
import { BodyLarge } from "../elements/text"
import TextBundle from "../../../../text_bundle"
import { Translator } from "../../../../translator"
import { ReactFactoryContext } from "../../factory"
import { useCallback, useEffect, useState } from "react"
import _ from "lodash"

import useUnloadWarning from "../hooks/useUnloadWarning"

import { TableContainer } from "../elements/table_container"

type Props = Weak<PropsUIPromptConsentForm> & ReactFactoryContext

export const ConsentForm = (props: Props): JSX.Element => {
  useUnloadWarning()
  const [tables, setTables] = useState<TableWithContext[]>(() => parseTables(props.tables))
  const [metaTables, setMetaTables] = useState<TableWithContext[]>(() => parseTables(props.metaTables))
  const { locale, resolve } = props
  const { description, donateQuestion, donateButton, cancelButton } = prepareCopy(props)
  const [isDonating, setIsDonating] = useState(false)

  useEffect(() => {
    setTables(parseTables(props.tables))
    setMetaTables(parseTables(props.metaTables))
  }, [props.tables])

  const updateTable = useCallback((tableId: string, table: TableWithContext) => {
    setTables((tables) => {
      const index = tables.findIndex((table) => table.id === tableId)
      if (index === -1) return tables

      const newTables = [...tables]
      newTables[index] = table
      return newTables
    })
  }, [])

  function rowCell(dataFrame: any, column: string, row: number): string {
    const text = String(dataFrame[column][`${row}`])
    return text
  }

  function columnNames(dataFrame: any): string[] {
    return Object.keys(dataFrame)
  }

  function columnCount(dataFrame: any): number {
    return columnNames(dataFrame).length
  }

  function rowCount(dataFrame: any): number {
    if (columnCount(dataFrame) === 0) {
      return 0
    } else {
      const firstColumn = dataFrame[columnNames(dataFrame)[0]]
      return Object.keys(firstColumn).length - 1
    }
  }

  function rows(data: any): PropsUITableRow[] {
    const result: PropsUITableRow[] = []
    const n = rowCount(data)
    for (let row = 0; row <= n; row++) {
      const id = `${row}`
      const cells = columnNames(data).map((column: string) => rowCell(data, column, row))
      result.push({ id, cells })
    }
    return result
  }

  function parseTables(tablesData: PropsUIPromptConsentFormTable[]): Array<PropsUITable & TableContext> {
    return tablesData.map((table) => parseTable(table))
  }

  function parseTable(tableData: PropsUIPromptConsentFormTable): PropsUITable & TableContext {
    const id = tableData.id
    const title = Translator.translate(tableData.title, props.locale)
    const description =
      tableData.description !== undefined ? Translator.translate(tableData.description, props.locale) : ""
    const deletedRowCount = 0
    const dataFrame = JSON.parse(tableData.data_frame)
    const headCells = columnNames(dataFrame).map((column: string) => column)
    const head: PropsUITableHead = {
      __type__: "PropsUITableHead",
      cells: headCells,
    }
    const body: PropsUITableBody = {
      __type__: "PropsUITableBody",
      rows: rows(dataFrame),
    }
    return {
      __type__: "PropsUITable",
      id,
      head,
      body,
      title,
      description,
      deletedRowCount,
      annotations: [],
      originalBody: body,
      deletedRows: [],
      visualizations: tableData.visualizations,
      folded: tableData.folded || false,
    }
  }

  function handleDonate(): void {
    setIsDonating(true)
    const value = serializeConsentData()
    resolve?.({ __type__: "PayloadJSON", value })
  }

  function handleCancel(): void {
    resolve?.({ __type__: "PayloadFalse", value: false })
  }

  function serializeConsentData(): string {
    const array = serializeTables().concat(serializeMetaData())
    return JSON.stringify(array)
  }

  function serializeMetaData(): any[] {
    return serializeMetaTables().concat(serializeDeletedMetaData())
  }

  function serializeTables(): any[] {
    return tables.map((table) => serializeTable(table))
  }

  function serializeMetaTables(): any[] {
    return metaTables.map((table) => serializeTable(table))
  }

  function serializeDeletedMetaData(): any {
    const rawData = tables
      .filter(({ deletedRowCount }) => deletedRowCount > 0)
      .map(({ id, deletedRowCount }) => `User deleted ${deletedRowCount} rows from table: ${id}`)

    const data = JSON.stringify(rawData)
    return { user_omissions: data }
  }

  function serializeTable({ id, head, body: { rows } }: PropsUITable): any {
    const data = rows.map((row) => serializeRow(row, head))
    return { [id]: data }
  }

  function serializeRow(row: PropsUITableRow, head: PropsUITableHead): any {
    assert(
      row.cells.length === head.cells.length,
      `Number of cells in row (${row.cells.length}) should be equals to number of cells in head (${head.cells.length})`
    )
    const keys = head.cells.map((cell) => cell)
    const values = row.cells.map((cell) => cell)
    return _.fromPairs(_.zip(keys, values))
  }

  return (
    <>
      <div className="max-w-3xl">
        {description.split("\n").map((line, index) => (
          <BodyLarge key={"description" + String(index)} text={line} />
        ))}
      </div>
      <div className="flex flex-col gap-16 w-full">
        <div className="grid gap-8 max-w-full">
          {tables.map((table) => {
            return (
              <TableContainer key={table.id} id={table.id} table={table} updateTable={updateTable} locale={locale} />
            )
          })}
        </div>
        <div>
          <BodyLarge margin="" text={donateQuestion} />

          <div className="flex flex-row gap-4 mt-4 mb-4">
            <PrimaryButton
              label={donateButton}
              onClick={handleDonate}
              color="bg-success text-white"
              spinning={isDonating}
            />
            <LabelButton label={cancelButton} onClick={handleCancel} color="text-grey1" />
          </div>
        </div>
      </div>
    </>
  )
}

interface Copy {
  description: string
  donateQuestion: string
  donateButton: string
  cancelButton: string
}

function prepareCopy({ donateQuestion, donateButton, description, locale }: Props): Copy {
  return {
    description: Translator.translate(description ?? defaultDescription, locale),
    donateQuestion: Translator.translate(donateQuestion ?? defaultDonateQuestionLabel, locale),
    donateButton: Translator.translate(donateButton ?? defaultDonateButtonLabel, locale),
    cancelButton: Translator.translate(cancelButtonLabel, locale),
  }
}

const defaultDonateQuestionLabel = new TextBundle()
  .add("en", "Do you want to donate the above data?")
  .add("nl", "Wilt u de bovenstaande gegevens doneren?")

const defaultDonateButtonLabel = new TextBundle().add("en", "Yes, donate").add("nl", "Ja, doneer")

const defaultDescription = new TextBundle()
  .add(
    "en",
    "Determine whether you would like to donate the data below. Carefully check the data and adjust when required. With your donation you contribute to the previously described research. Thank you in advance."
  )
  .add(
    "nl",
    "Bepaal of u de onderstaande gegevens wilt doneren. Bekijk de gegevens zorgvuldig en pas zo nodig aan. Met uw donatie draagt u bij aan het eerder beschreven onderzoek. Alvast hartelijk dank."
  )

const cancelButtonLabel = new TextBundle().add("en", "No").add("nl", "Nee")
