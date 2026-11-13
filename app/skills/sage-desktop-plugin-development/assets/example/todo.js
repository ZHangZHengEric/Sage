const {call, ready} = window.sageDesktop;
const form = document.querySelector('form');
const input = form.querySelector('input');
const list = document.querySelector('ul');
const status = document.querySelector('output');
const draft = document.querySelector('#draft');
let items = [];

function render() {
  list.replaceChildren(...items.map(item => {
    const row = document.createElement('li');
    row.textContent = item;
    return row;
  }));
  draft.disabled = items.length === 0;
}

function report(error) { status.textContent = error.message; }

form.addEventListener('submit', async event => {
  event.preventDefault();
  const value = input.value.trim();
  if (!value) return;
  try {
    const next = [...items, value];
    await call('storage.set', {key: 'items', value: next});
    items = next;
    input.value = '';
    render();
  } catch (error) { report(error); }
});
draft.addEventListener('click', () => {
  call('draft.insert', {text: items.map(item => `- ${item}`).join('\n')}).catch(report);
});
ready.then(() => call('storage.get', {key: 'items'})).then(value => {
  items = Array.isArray(value) ? value : [];
  render();
}).catch(report);
