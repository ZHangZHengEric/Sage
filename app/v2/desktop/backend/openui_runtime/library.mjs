import { createLibrary, defineComponent } from '@openuidev/lang-core';
import { z } from 'zod';

// Property order is the OpenUI positional argument order. Generate the prompt
// and schema from this same library; the Flutter renderer consumes these names.
const children = z.array(z.any()).min(1).max(100);
const text = z.string().max(8000);
const identifier = z.string().regex(/^[A-Za-z][A-Za-z0-9_-]{0,63}$/);
const tone = z.enum(['neutral', 'info', 'success', 'warning', 'error']).default('neutral');
const finite = z.number().finite().min(-1e12).max(1e12);
// Component references are normalized by worker.mjs; Python validates their
// numeric types, dependencies and bounds before any surface becomes interactive.
const numeric = z.union([finite, identifier, z.object({ component: z.enum(['NumberInput', 'Slider', 'Computed']), props: z.record(z.string(), z.any()), id: identifier.optional() })]);
const calculationInput = z.union([numeric, z.object({ component: z.literal('CheckboxGroup'), props: z.record(z.string(), z.any()), id: identifier.optional() })]);
const options = z.array(text).min(1).max(100);
const components = {
  Deck: z.object({ title: text, children: z.array(z.any()).min(1).max(40) }),
  Slide: z.object({ title: z.string().max(40), children: z.array(z.any()).max(4), layout: z.enum(["cover", "content", "split"]).default("content"), accent: z.enum(["blue", "rose", "emerald", "amber"]).default("blue") }),
  Stack: z.object({ children }),
  Row: z.object({ children }),
  Card: z.object({ title: text, children }),
  Text: z.object({ content: text }),
  Table: z.object({ columns: z.array(text).min(1).max(20), rows: z.array(z.array(z.union([text, z.number(), z.boolean(), z.null()]))).max(200) }),
  Input: z.object({ name: identifier, label: text, value: text.optional().default(''), required: z.boolean().optional().default(false) }),
  Select: z.object({ name: identifier, label: text, options: z.array(text).min(1).max(100), value: text.optional().default(''), required: z.boolean().optional().default(false) }),
  Toggle: z.object({ name: identifier, label: text, value: z.boolean().optional().default(false) }),
  Button: z.object({ action: identifier, label: text }),
  Heading: z.object({ content: text, level: z.number().int().min(1).max(3).default(2) }),
  Badge: z.object({ label: text, tone }),
  Metric: z.object({ label: text, value: text, change: text.default(''), tone }),
  Divider: z.object({}),
  Image: z.object({ url: z.string().max(2048), alt: text, height: z.number().min(80).max(600).default(240) }),
  Progress: z.object({ label: text, value: numeric, tone }),
  Alert: z.object({ content: text, tone }),
  Tabs: z.object({ children: children }),
  Tab: z.object({ label: text, children }),
  Accordion: z.object({ children: children }),
  Section: z.object({ title: text, children }),
  NumberInput: z.object({ name: identifier, label: text, value: finite.default(0), min: finite.default(0), max: finite.default(1000000), step: z.number().positive().max(1e12).default(1) }),
  Slider: z.object({ name: identifier, label: text, value: finite.default(50), min: finite.default(0), max: finite.default(100), step: z.number().positive().max(1e12).default(1) }),
  DateInput: z.object({ name: identifier, label: text, value: text.default(''), required: z.boolean().default(false) }),
  CheckboxGroup: z.object({ name: identifier, label: text, options, value: z.array(text).max(100).default([]), required: z.boolean().default(false) }),
  RadioGroup: z.object({ name: identifier, label: text, options, value: text.default(''), required: z.boolean().default(false) }),
  Chart: z.object({ title: text, type: z.enum(['line', 'bar', 'pie']), labels: z.array(text).min(1).max(100), series: z.array(z.object({ name: text, values: z.array(numeric).min(1).max(100) })).min(1).max(8) }),
  Computed: z.object({ label: text, operation: z.enum(['sum', 'difference', 'product', 'divide', 'percent', 'ratioPercent', 'count', 'compoundGrowth', 'loanPayment']), inputs: z.array(calculationInput).min(1).max(16), precision: z.number().int().min(0).max(6).default(2), prefix: text.default(''), suffix: text.default('') }),
  Timeline: z.object({ items: z.array(z.object({ label: text, value: text, tone })).min(1).max(50) }),
  Diagram: z.object({ title: text, nodes: z.array(z.object({ id: identifier, label: text })).min(1).max(20), edges: z.array(z.array(identifier).length(2)).max(40) }),
};
const definitions = Object.fromEntries(Object.entries(components).map(([name, props]) => [name, defineComponent({ name, props, component: () => null })]));
// Use the official component-slot API: a generic Zod object describes data,
// while .ref tells the parser and generated prompt to expect component calls.
for (const [name, childNames, min, max] of [
  ['Slide', ['Text', 'Metric', 'Table', 'Chart'], 0, 4],
  ['Deck', ['Slide'], 1, 40],
  ['Tabs', ['Tab'], 1, 100],
  ['Accordion', ['Section'], 1, 100],
]) {
  const refs = childNames.map(child => definitions[child].ref);
  const slot = refs.length === 1 ? refs[0] : z.union(refs);
  definitions[name] = defineComponent({ name, props: components[name].extend({ children: z.array(slot).min(min).max(max) }), component: () => null });
}
export const library = createLibrary({ components: Object.values(definitions) });
export const schema = library.toJSONSchema();
export const prompt = library.prompt().replace(
  'Your ENTIRE response must be valid openui-lang code — no markdown, no explanations, just openui-lang.',
  'Place UI programs inside a fenced Markdown block with the exact language openui. Ordinary prose outside the block remains Markdown. The Desktop renders the block progressively as tokens arrive.',
).replaceAll('Root(...)', 'Stack(...)').replace('every program must define `root = Stack(...)`', 'every program must assign `root` to a registered component; use `Deck` for presentations').replace('Unreferenced variables are silently dropped and will NOT render.', 'Unreferenced declarations fail final validation.').replaceAll('root = Stack(...)', 'the root assignment').replaceAll('the the root assignment', 'the root assignment') + `\nSage Desktop v2 component library: only the components above and static literals/references. No $state, expressions, Query, Mutation, functions, HTML, CSS, scripts or tool actions (Image accepts public HTTPS image URLs only). Input state is owned by Sage. Button(action, label) submits all fields as the next user turn; it cannot execute tools. Do not add subtitles or field descriptions. Let the UI carry the answer. By default emit only the openui block; omit introductory and closing prose, repeated table data, and form instructions already clear from labels. Use at most one short sentence outside the block only for a necessary conclusion, exception, or next step. Choose layout for the task: Row for related summaries or alternatives, Table for precise comparisons, Card for meaningful groups. Avoid a Card around every line or unnecessary nested Cards. Group related fields and place the primary action after them. Use short, concrete labels; Sage supplies all visual styling. Metric displays a fixed text snapshot and does not accept component references. Computed is itself a visible result card with a label, formatted value and reactive local calculation; place it directly in the layout, without wrapping it in Metric or Text. When results depend on editable inputs, use Computed result cards and bind every dependent chart value to numeric fields or Computed results; never substitute static snapshots or a submit-and-recalculate workflow for requested immediate updates. Use Metric and Chart for dashboards; use Tabs/Tab and Accordion/Section for long grouped content, not hidden required forms. Each Chart series must contain exactly one value per category label, in the same order; values may also reference numeric fields or Computed results for instant local updates. Pie uses one nonnegative series. NumberInput and Slider require min < max and an in-range value. DateInput uses YYYY-MM-DD. Computed is a local, safe calculation that updates immediately when numeric fields change: for numeric operations, inputs are numeric literals, NumberInput/Slider references or Computed references. Selection counting has the explicit count operation described below. Prefer direct component-variable references for dependencies, including intermediate Computed nodes. Quoted field names and Computed identifiers only resolve nodes already reachable from the root through component references; a quoted name does not make a separate statement reachable. Every declared component must be reachable. Computed results can feed other Computed components and Chart values; dependencies must be acyclic and resolve to rendered numeric inputs. For selection tracking use Computed count with 1-16 CheckboxGroup references or quoted checkbox field names; it returns the total number of selected options. Do not pass checkbox arrays to sum or other numeric operations. RadioGroup is a string, not a number. ratioPercent accepts [completed, total] and returns completed / total * 100; use it for completion rates. Existing percent means base * rate / 100, not completion ratio. Progress accepts numeric literals, numeric fields or Computed references and updates locally, clamped to 0-100 for display. Bind progress to the same count/ratio calculation as the displayed completion metric. No arbitrary expressions or conditional execution are supported. Preserve the units and meaning of each input. Operations sum/product accept 1-16 inputs; difference/divide/percent accept exactly two; compoundGrowth accepts [principal, annualRatePercent, years]; loanPayment accepts [principal, annualRatePercent, months]. percent returns base * rate / 100. Formatting prefixes and suffixes never change the numeric value; a percentage label requires an explicitly scaled value in percentage units. Do not invent formulas, expressions, or implicit units. Input fields do not require a Button. For local exploration or calculation, omit submission buttons: Computed and bound Chart values update on input changes without a model request. Include a Button only when the task requires sending the chosen values back to the assistant for a distinct follow-up; its label must clearly communicate that handoff, never imply local calculation. All children arguments MUST be arrays, even one child: Tab("Overview", [table]), Section("Details", [text]), Card("Result", [metric]). Never pass a single component directly as children. Tabs contains only Tab; Accordion contains only Section. Use Image only when the user or verified source supplies a public HTTPS image URL; never invent URLs. For presentations/PPT use root = Deck("Title", [slide1, slide2]) and forward-defined Slide("Title", [text, chart], "split", "blue"). Deck contains only Slide; never nest decks. Slide supports 0-4 direct Text, Metric, Table or Chart children only. Titles max 40 characters (cover 32); Text max 240 (120 for a split with 3-4 blocks); Metric label max 40/value max 40/change max 40; Table max 5 columns and 6 rows, cells max 40 characters; Tables/charts require at most two blocks per slide. Chart title max 40 and series name max 20; max 12 labels (max 20 characters) and 3 numeric-only series. Keep content concise; split overflowing material across slides. Cover supports at most one Text, content at most two blocks, split at most four blocks. Use cover for opening/closing, content for a full-width chart, split for comparisons. Accents blue/rose/emerald/amber add variety. Fixed 16:9 native preview streams while generating; the host enables editable PPTX export after final validation, without tools. For forms, finish the message after the block and wait for the next user turn.\n`;


// Slide source is the single document used by both preview and editable export.
