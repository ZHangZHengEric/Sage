import test from 'node:test';
import assert from 'node:assert/strict';
import { parseSurface } from './worker.mjs';
import { prompt } from './library.mjs';

test('official streaming parser renders incomplete strings and forward refs', () => {
  const source = 'root = Card("Trip", [summary, table])\nsummary = Text("Hello")\ntable = Table(["City"], [["Shanghai"]])';
  let seenPartialText = false;
  let code = '';
  for (const token of source) {
    code += token;
    const tree = parseSurface(code, false, 'token-stream');
    if (tree?.props.children?.[0]?.props.content === 'He') seenPartialText = true;
  }
  assert.equal(seenPartialText, true);
  const tree = parseSurface(source, true, 'token-stream');
  assert.equal(tree.props.children[1].props.rows[0][0], 'Shanghai');
});

test('complete validation rejects malformed source and executable language features', () => {
  for (const code of ['root = Text("Hello', 'root = Missing("x")', 'root = Card("X", [missing])', 'root = Text($secret)', 'root = Query("file_write", {})', 'root = Text("Hi")\norphan = Text("lost")']) {
    assert.throws(() => parseSurface(code, true));
  }
});

test('stream identities do not mix parallel messages', () => {
  assert.equal(parseSurface('root = Text("A', false, 'a').props.content, 'A');
  assert.equal(parseSurface('root = Text("B', false, 'b').props.content, 'B');
  assert.equal(parseSurface('root = Text("AA', false, 'a').props.content, 'AA');
});

test('generated streaming instructions name a registered root and minimize prose', () => {
  assert.doesNotMatch(prompt, /Root\(/);
  assert.match(prompt, /assign `root` to a registered component/);
  assert.match(prompt, /root = Deck\(/);
  assert.doesNotMatch(prompt, /every program must define `root = Stack/);
  assert.match(prompt, /By default emit only the openui block/);
  assert.equal(parseSurface('root = Stack([Text("Hi")])', true).component, 'Stack');
});

import { gallery } from './gallery.mjs';
import { schema } from './library.mjs';
test('expanded examples cover every registered component and stream incrementally', () => {
  const seen = new Set();
  const visit = node => { seen.add(node.component); for (const child of node.props.children ?? []) visit(child); };
  for (const item of gallery) {
    for (let length = 1; length <= item.code.length; length += 7) parseSurface(item.code.slice(0, length), false, item.name);
    visit(parseSurface(item.code, true, item.name));
  }
  assert.deepEqual([...seen].sort(), Object.keys(schema.$defs).sort());
});


test('numeric component references retain statement identities and normalize recursively', () => {
  const sample = gallery.find(item => item.name === 'chained-calculator');
  const tree = parseSurface(sample.code);
  const total = tree.props.children[0].props.children[0];
  assert.equal(total.id, 'total');
  assert.equal(total.props.inputs[0].component, 'Computed');
  assert.equal(total.props.inputs[0].props.inputs[0].component, 'NumberInput');
  assert.equal(total.props.inputs[0].props.inputs[0].props.name, 'days');
});
