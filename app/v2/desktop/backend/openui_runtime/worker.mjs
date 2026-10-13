import { createParser, createStreamingParser } from '@openuidev/lang-core';
import { schema } from './library.mjs';

const streams = new Map();
export function parseSurface(code, complete = true, streamId = "default") {
  if (typeof code !== 'string' || Buffer.byteLength(code, 'utf8') > 65536) throw Error('UI source exceeds 64 KiB');
  // Declarative programs use registered components, not the language evaluator.
  const unquoted = code.replace(/"(?:\\.|[^"\\])*"/g, '""');
  if (/\$|@|\b(?:Query|Mutation|Action)\s*\(/.test(unquoted)) throw Error('Reactive expressions and executable actions are unsupported');
  let parser = streams.get(streamId);
  if (!parser) {
    parser = createStreamingParser(schema);
    if (streams.size >= 64) streams.delete(streams.keys().next().value);
    streams.set(streamId, parser);
  }
  const result = complete ? createParser(schema).parse(code) : parser.set(code);
  if (complete) streams.delete(streamId);
  if (result.rootExpression || (complete && (!result.root || result.meta.incomplete || result.meta.unresolved.length || result.meta.orphaned.length || result.meta.errors.length)) || Object.keys(result.stateDeclarations).length || result.queryStatements.length || result.mutationStatements.length) {
    throw Error('Invalid OpenUI source: ' + JSON.stringify(result.meta));
  }
  if (!result.root) return null;
  let count = 0;
  const walk = (node, depth = 0) => {
    if (++count > 300 || depth > 12) throw Error('UI tree exceeds limits');
    if (node?.type !== 'element' || node.hasDynamicProps !== false || !schema.$defs[node.typeName]) {
      // A streamed minus sign is temporarily classified as an expression by
      // the official parser. Withhold that node until its literal is complete.
      if (!complete) return null;
      throw Error('Only complete static registered components are allowed');
    }
    if (complete && node.partial) throw Error('Incomplete component');
    const props = { ...node.props };
    if ('children' in props) props.children = (Array.isArray(props.children) ? props.children : []).filter(Boolean).map(child => walk(child, depth + 1)).filter(Boolean);
    const numeric = value => value?.type === 'element' ? walk(value, depth + 1) : value;
    if (node.typeName === 'Progress') props.value = numeric(props.value);
    if (node.typeName === 'Computed' && Array.isArray(props.inputs)) props.inputs = props.inputs.map(numeric);
    if (node.typeName === 'Chart' && Array.isArray(props.series)) props.series = props.series.map(series => ({ ...series, values: Array.isArray(series.values) ? series.values.map(numeric) : [] }));
    return { component: node.typeName, props, ...(['NumberInput', 'Slider', 'Computed', 'CheckboxGroup'].includes(node.typeName) && node.statementId ? {id: node.statementId} : {}) };
  };
  return walk(result.root);
}

if (process.argv[1]?.endsWith('worker.mjs') || process.argv[1]?.endsWith('worker.cjs')) {
  void (async () => {
    const { createInterface } = await import('node:readline');
    for await (const line of createInterface({ input: process.stdin, crlfDelay: Infinity })) {
      try {
        if (Buffer.byteLength(line) > 100000) throw Error('Request exceeds limits');
        const { code, complete = true, stream_id = "default" } = JSON.parse(line);
        process.stdout.write(JSON.stringify({ tree: parseSurface(code, complete, stream_id) }) + '\n');
      } catch (error) { process.stdout.write(JSON.stringify({ error: error.message }) + '\n'); }
    }
  })();
}
