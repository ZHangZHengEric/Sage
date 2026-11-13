const {ready, call} = window.sageDesktop;
const output = document.querySelector('#result');

async function show(action) {
  try {
    await ready;
    const value = await action();
    if (value != null) output.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  } catch (error) {
    output.textContent = error.message;
  }
}

document.querySelector('#workspace').onclick = () => show(async () => {
  const workspace = await call('context.read');
  return workspace?.workspaceName;
});
document.querySelector('#file').onclick = () => show(async () => {
  const file = await call('file.read');
  if (!file) return null;
  const bytes = Uint8Array.from(atob(file.base64), char => char.charCodeAt(0));
  return `${file.name}\n${new TextDecoder().decode(bytes).slice(0, 2000)}`;
});
document.querySelector('#fetch').onclick = () => show(async () => {
  const result = await call('https.request', {endpoint: 'example'});
  if (!result) return null;
  if (result.status !== 200) return `HTTP ${result.status}`;
  const {full_name, stargazers_count, open_issues_count} = JSON.parse(result.body);
  return `${full_name}\n星标 ${stargazers_count}\n未关闭问题 ${open_issues_count}`;
});
