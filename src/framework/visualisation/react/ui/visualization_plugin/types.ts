import { z } from "zod"

// In order to work towards making visualizations a plugin, we postpone type checking
// until the visualization is actually used. We use zod to define every type, so that
// we can parse the visualizations argument in PropsUIPromptConsentFormTable.

// Matching types from Feldspar
// We can either import these from Feldspare, or keep visualization plugin separate b
// duplicating the types here. Currently opting for duplication to avoid complexity
// (and if input format changes, the plugin would break regardless)

export const zTranslatable = z.record(z.string())
export type Translatable = z.infer<typeof zTranslatable>

export const zLabel = z.union([zTranslatable, z.string()])
export type Label = z.infer<typeof zLabel>

// Table type, but only taking what we need
export const zTable = z.object({
  id: z.string(),
  head: z.object({ cells: z.array(z.string()) }),
  body: z.object({ rows: z.array(z.object({ id: z.string(), cells: z.array(z.string()) })) }),
})
export type Table = z.infer<typeof zTable>

// Visualization Types

export const zVisualizationProps = z.object({
  title: zTranslatable,
  height: z.number().optional(),
})
export type VisualizationProps = z.infer<typeof zVisualizationProps>

export const zAggregationFunction = z.enum(["count", "mean", "sum", "count_pct", "pct"])
export type AggregationFunction = z.infer<typeof zAggregationFunction>

export const zDateFormat = z.enum([
  "auto",
  "year",
  "quarter",
  "month",
  "day",
  "hour",
  "month_cycle",
  "weekday_cycle",
  "hour_cycle",
])
export type DateFormat = z.infer<typeof zDateFormat>

export const zChartVisualizationType = z.enum(["line", "bar", "area"])
export type ChartVisualizationType = z.infer<typeof zChartVisualizationType>

export const zTextVisualizationType = z.enum(["wordcloud"])
export type TextVisualizationType = z.infer<typeof zTextVisualizationType>

// Chart Visualizations

// External types (need schema)
export const zAxis = z.object({
  label: zLabel.optional(),
  column: z.string(),
})
export type Axis = z.infer<typeof zAxis>

export const zAggregationGroup = z.object({
  label: zLabel.optional(),
  column: z.string(),
  dateFormat: zDateFormat.optional(),
  range: z.array(z.number()).optional(),
  levels: z.array(z.string()).optional(),
})
export type AggregationGroup = z.infer<typeof zAggregationGroup>

export const zAggregationValue = z.object({
  label: zLabel.optional(),
  column: z.string().optional().default(".COUNT"),
  aggregate: zAggregationFunction.optional(),
  group_by: z.string().optional(),
  z: z.string().optional(),
  zAggregate: zAggregationFunction.optional(),
  addZeroes: z.boolean().optional(),
})
export type AggregationValue = z.infer<typeof zAggregationValue>

export const zChartVisualization = zVisualizationProps.merge(
  z.object({
    type: zChartVisualizationType,
    group: zAggregationGroup,
    values: z.array(zAggregationValue),
  })
)
export type ChartVisualization = z.infer<typeof zChartVisualization>

// Internal types
export type TickerFormat = "percent" | "default"
export type XType = "string" | "date"

export interface AxisSettings {
  id: string
  label: Translatable | string
  tickerFormat: TickerFormat
}

export interface ChartVisualizationData {
  type: ChartVisualizationType
  data: Array<Record<string, any>>
  xKey: string
  xLabel: string | Translatable | undefined
  yKeys: Record<string, AxisSettings>
}

// Text Visualizations

// External types (need schema)

export const zTextVisualization = zVisualizationProps.merge(
  z.object({
    type: zTextVisualizationType,
    textColumn: z.string(),
    valueColumn: z.string().optional(),
    tokenize: z.boolean().optional(),
    extract: z.enum(["url_domain"]).optional(),
  })
)
export type TextVisualization = z.infer<typeof zTextVisualization>

// Internal types

export interface ScoredTerm {
  text: string
  value: number
  importance: number
  rowIds?: string[]
}

export interface TextVisualizationData {
  type: TextVisualizationType
  topTerms: ScoredTerm[]
}

// Visualization Type union

export type VisualizationData = ChartVisualizationData | TextVisualizationData

export const zVisualizationType = z.union([zChartVisualization, zTextVisualization])
export type VisualizationType = z.infer<typeof zVisualizationType>
