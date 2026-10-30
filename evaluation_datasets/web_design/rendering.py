"""Deterministic browser captures. No website bytes are fetched from the network."""
from html.parser import HTMLParser
from io import BytesIO
import hashlib
import json
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from evaluation_datasets.web_design.workspace import file_path

ORIGIN = 'http://web-design.invalid'
VIEWPORTS = (('desktop', 1440, 1000), ('tablet', 768, 1024), ('mobile', 390, 844))
MAX_PAGES = 3
# Repeatable per page, but nonconstant: unique random selection must terminate.
DETERMINISTIC_RANDOM = """(() => {
    let state = 0x6d2b79f5;
    Math.random = () => {
        state = (state + 0x6d2b79f5) >>> 0;
        let value = state;
        value = Math.imul(value ^ (value >>> 15), value | 1);
        value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
        return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
    };
})();"""


def progress(directory, stage, **details):
    import time
    path = Path(directory) / 'render-progress.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.monotonic()
    previous = json.loads(path.read_text()) if path.exists() and stage != 'browser_queue' else {}
    started = previous.get('started_at', now)
    entry = {'stage': stage, 'elapsed_seconds': round(now - started, 3), **details}
    path.write_text(json.dumps({**entry, 'started_at': started,
        'history': [*previous.get('history', []), entry][-64:]}))



class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(value for key, value in attrs if key == 'href' and value)


def pages(files):
    """Homepage, then linked local HTML pages in breadth-first document order."""
    selected = ['index.html']
    for name in selected:
        parser = Links()
        parser.feed(files[name])
        for link in parser.links:
            url = urlsplit(urljoin(ORIGIN + '/' + name, link))
            path = unquote(url.path.lstrip('/'))
            if url.netloc == 'web-design.invalid' and path in files and path.endswith('.html') and path not in selected:
                selected.append(path)
                if len(selected) == MAX_PAGES:
                    return selected
    return selected


def frozen(path, media_type):
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'size_bytes': path.stat().st_size, 'media_type': media_type}


def sheet(frames, label):
    from PIL import Image, ImageDraw
    import math
    images = [Image.open(BytesIO(frame)).convert('RGB') for frame in frames]
    n = math.ceil(math.sqrt(len(images)))
    cell = min(960, 1920 // n)
    result = Image.new('RGB', (n * cell, n * cell), '#e8e8e8')
    draw = ImageDraw.Draw(result)
    for index, im in enumerate(images):
        scale = min((cell - 12) / im.width, (cell - 36) / im.height, 1)
        im = im.resize((round(im.width * scale), round(im.height * scale)))
        x, y = index % n * cell, index // n * cell
        draw.text((x + 6, y + 7), f'{label} / frame {index + 1}', fill='#111111')
        result.paste(im, (x + (cell - im.width) // 2, y + 30 + (cell - 36 - im.height) // 2))
    return result


def encode_sheet(image, budget):
    for _ in range(8):
        for quality in (85, 70, 55):
            stream = BytesIO()
            image.save(stream, 'JPEG', quality=quality, optimize=True)
            if stream.tell() <= budget:
                return stream.getvalue()
        image = image.resize((max(1, round(image.width * .8)), max(1, round(image.height * .8))))
    raise ValueError('Cannot fit visual evidence in the model request budget')


async def render(files, directory):
    from evaluation_datasets.web_design.browser_slots import browser_slot
    progress(directory, 'browser_queue')
    try:
        async with browser_slot():
            progress(directory, 'browser_acquired')
            result = await _render(files, directory)
            progress(directory, 'completed')
            return result
    except BaseException as error:
        # Preserve the last phase without dumping submitted source/provider messages.
        path = Path(directory) / 'render-progress.json'
        state = json.loads(path.read_text())
        progress(directory, state['stage'], error_type=type(error).__name__)
        raise


async def _render(files, directory):
    from playwright.async_api import async_playwright
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    captures, sheets, declared = [], [], []
    selected = pages(files)
    # These original bytes remain available for inspection and exact rerendering.
    for name, content in files.items():
        file_path(name)
        path = directory / 'source' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        # Native file tools write UTF-8 text. Source evidence is always text,
        # including auxiliary scripts/docs and image-looking filenames. Browser
        # response MIME types are chosen separately when rendering resources.
        declared.append(frozen(path, 'text/plain'))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            for viewport, width, height in VIEWPORTS:
                context = await browser.new_context(viewport={'width': width, 'height': height},
                    device_scale_factor=1, color_scheme='light', reduced_motion='reduce', locale='en-US',
                    timezone_id='UTC', service_workers='block', accept_downloads=False)
                context.set_default_timeout(8000)
                blocked = set()

                async def route_request(route):
                    url = urlsplit(route.request.url)
                    path = unquote(url.path.lstrip('/')) or 'index.html'
                    if (url.scheme == 'http' and url.netloc == 'web-design.invalid' and path in files
                            and route.request.method in {'GET', 'HEAD'}):
                        await route.fulfill(status=200, body=files[path].encode(), headers={
                            'Content-Type': (mimetypes.guess_type(path)[0] or 'text/plain') + '; charset=utf-8',
                            'Content-Security-Policy': "default-src 'self' data: blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; connect-src 'none'; frame-src 'none'; worker-src 'none'",
                        })
                    else:
                        # Record counts, not URLs: a submitted URL may contain secrets or misleading judge text.
                        blocked.add(route.request.url)
                        await route.abort()

                await context.route('**/*', route_request)
                await context.route_web_socket('**/*', lambda socket: socket.close())
                await context.add_init_script(DETERMINISTIC_RANDOM)
                try:
                    for page_index, name in enumerate(selected):
                        page = await context.new_page()
                        resources, page_errors = [], []
                        page.on('response', lambda response: resources.append({
                            'path': urlsplit(response.url).path,
                            'status': response.status,
                            'type': response.request.resource_type}))
                        page.on('pageerror', lambda error: page_errors.append(str(error)[:400]))
                        await page.clock.install(time=1767225600000)
                        progress(directory, 'navigation', viewport=viewport, page=page_index)
                        await page.goto(ORIGIN + '/' + name, wait_until='load', timeout=12000)
                        await page.evaluate('() => document.fonts.ready')
                        await page.add_style_tag(content='*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important;scroll-behavior:auto!important}')
                        await page.wait_for_timeout(300)
                        measured = await page.evaluate('() => Math.max(document.body?.scrollHeight || 0, document.documentElement.scrollHeight)')
                        # Cap lazy-loading scans; still include the real measured bottom.
                        for offset in range(0, min(measured, 12000), height):
                            await page.evaluate('(y) => scrollTo(0,y)', offset)
                            await page.wait_for_timeout(40)
                        measured = await page.evaluate('() => Math.max(document.body?.scrollHeight || 0, document.documentElement.scrollHeight)')
                        bottom = max(0, measured - height)
                        offsets = sorted({0, bottom // 3, 2 * bottom // 3, bottom})
                        frames, screenshots = [], []
                        for position, offset in enumerate(offsets):
                            await page.evaluate('(y) => scrollTo(0,y)', offset)
                            await page.wait_for_timeout(120)
                            progress(directory, 'scroll_screenshot', viewport=viewport, page=page_index, frame=position)
                            frame = await page.screenshot(type='png', animations='disabled', timeout=8000)
                            path = directory / f'{viewport}-{page_index}-{position}.png'
                            path.write_bytes(frame)
                            frames.append(frame)
                            screenshots.append({'file': path.name, 'scroll_y': offset})
                            declared.append(frozen(path, 'image/png'))
                        capture = {'viewport': viewport, 'width': width, 'height': height, 'page': page_index,
                            'source_page': name, 'document_height': measured, 'screenshots': screenshots,
                            'blocked_requests': len(blocked), 'resources': list(resources),
                            'page_errors': list(page_errors),
                            'stylesheets': await page.evaluate('''() => [...document.styleSheets].map(s => {
                                try { return {inline: !s.href, rules:s.cssRules.length}; }
                                catch { return {inline: !s.href, unreadable:true}; }
                            })''')}
                        captures.append(capture)
                        sheets.append((sheet(frames, f'{viewport} {width}x{height} / page {page_index + 1}'), capture))
                        if page_index == 0:
                            state_capture, state_frames = await interaction_frames(page, directory, viewport, declared)
                            if state_capture['actions']:
                                state_capture.update(resources=list(resources), page_errors=list(page_errors))
                                captures.append(state_capture)
                            if state_frames:
                                sheets.append((sheet(state_frames, f'{viewport} {width}x{height} / interaction states'), state_capture))
                        await page.close()
                finally:
                    await context.close()
        finally:
            await browser.close()
    # Both sides plus base64 and text fit the native Eval Agent's 8 MiB visual input budget.
    for index, (image, capture) in enumerate(sheets):
        path = directory / f'contact-{index}.jpg'
        path.write_bytes(encode_sheet(image, 150_000))
        capture['contact_file'] = path.name
        declared.append(frozen(path, 'image/jpeg'))
    manifest = directory / 'screenshots.json'
    manifest.write_text(json.dumps(captures, indent=2), encoding='utf-8')
    declared.append(frozen(manifest, 'application/json'))
    return {'status': 'rendered', 'captures': captures}, declared


async def interaction_frames(page, directory, viewport, declared):
    """Two bounded, semantic UI probes; no task-specific answers or judge calls."""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    controls = page.locator('button:not([type="submit"]):not([type="reset"]), '
        '[role="tab"], summary, input[type="range"], select')
    frames, screenshots, actions = [], [], []
    # Inspect a bounded DOM prefix; only visible, enabled controls are eligible.
    for index in range(min(await controls.count(), 24)):
        if len(actions) == 2:
            break
        control = controls.nth(index)
        try:
            if not await control.is_visible() or not await control.is_enabled():
                continue
            kind = await control.evaluate('(e) => ({tag:e.tagName.toLowerCase(),type:e.type,form:!!e.form})')
            if kind['tag'] == 'button' and kind['form'] and kind['type'] != 'button':
                continue
            progress(directory, 'interaction', viewport=viewport, control=index)
            await control.scroll_into_view_if_needed(timeout=1500)
            before = await page.screenshot(type='png', animations='disabled', timeout=8000)
            if kind['tag'] == 'input':
                await control.evaluate('''e => {const a=Number(e.min||0),b=Number(e.max||100);
                    e.value=String(a+(b-a)*.75);e.dispatchEvent(new Event('input',{bubbles:true}));
                    e.dispatchEvent(new Event('change',{bubbles:true}));}''')
            elif kind['tag'] == 'select':
                values = await control.locator('option:not([disabled])').evaluate_all('(es)=>es.map(e=>e.value)')
                if len(values) < 2:
                    continue
                await control.select_option(values[1], timeout=1500)
            else:
                await control.click(timeout=1500, no_wait_after=True)
            await page.clock.run_for(250)
            after = await page.screenshot(type='png', animations='disabled', timeout=8000)
            actions.append({'control_index': index, 'kind': kind['tag'], 'state_changed': before != after})
            for state, data in [('before', before), ('after', after)]:
                path = directory / f'{viewport}-interaction-{len(actions)}-{state}.png'
                path.write_bytes(data)
                declared.append(frozen(path, 'image/png'))
                frames.append(data)
                screenshots.append({'file': path.name, 'action': len(actions), 'state': state})
        except PlaywrightTimeoutError as error:
            # Unexplored controls are coverage gaps, not automatic task failures.
            actions.append({'control_index': index, 'status': 'not_captured', 'error': type(error).__name__})
    return {'viewport': viewport, 'source_page': 'index.html', 'kind': 'interaction',
        'actions': actions, 'screenshots': screenshots}, frames
