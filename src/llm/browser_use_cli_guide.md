# Browser control: browser-use CLI

You control a browser that is already open and already logged in. Drive it only
through the Bash tool with the `browser-use` command. Pass Python on stdin as a
heredoc. The helpers below are pre-imported:

```bash
browser-use <<'PY'
new_tab("https://example.com")
wait_for_load()
print(page_info())
PY
```

Rules:
- Your first navigation is `new_tab(url)`. Later calls reuse that tab, so use
  `goto_url(url)` after that. Never call `activate_tab`.
- Each call is a fresh Python run. Variables do not survive between calls, but
  the tab and the page do.
- Print only what you need. Filter big results in Python before printing.
- After every navigation or submit, call `wait_for_load()` and check the result.

Helpers:
- `new_tab(url)`, `goto_url(url)`, `wait_for_load(timeout=15.0)`, `wait(seconds)`
- `page_info()`: url, title, viewport size and scroll position
- `js(expression)`: run JavaScript in the page and return the value
- `wait_for_element(selector, timeout=10.0, visible=False)`
- `fill_input(selector, text, clear_first=True)`: fill a text field by CSS selector
- `click_at_xy(x, y)`, `type_text(text)`, `press_key(key)`, `scroll(x, y, dy=-300)`
- `upload_file(selector, path)`: attach a local file to an `<input type="file">`
- `cdp("Domain.method", **params)`: raw Chrome DevTools Protocol
- `capture_screenshot(path)`: only when layout matters; prefer text

Finding and clicking elements:
- Prefer the accessibility tree. `cdp("Accessibility.getFullAXTree")["nodes"]`
  gives each element's role, name and `backendDOMNodeId`. Filter it in Python.
- To click a node: `q = cdp("DOM.getBoxModel", backendNodeId=n)["model"]["content"]`,
  then `click_at_xy(sum(q[0::2])/4, sum(q[1::2])/4)`. Scroll first if the
  numbers are negative or past the viewport.
- For simple forms, `js("document.querySelector('...')...")` is often faster.
- Native `<select>`: set the value with `js(...)` and dispatch a `change` event,
  then read it back. Custom dropdowns: click to open, then click the option.
- Text boxes with suggestions: after typing, look for the suggestion list and
  pick the matching option.
- Iframes: application forms are often inside one. Check `js("document.querySelectorAll('iframe').length")`
  and read `iframe.src` to find the form.

If a command fails or times out, inspect the page again before retrying. Do not
open other browsers, do not run other programs, and do not try to fix the
browser connection yourself. If the browser is unreachable, stop and report it.
