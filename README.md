# @hummingbirdworks/proxy

A [mitmproxy](https://www.mitmproxy.org/)-based dev proxy that redirects
Dataverse / Dynamics 365 **web resources** and **PCF control** assets to your
local dev builds or a running dev server (e.g. Vite), so you can iterate
locally without deploying on every change.

## Prerequisites

- **Node.js** >= 16.
- **mitmproxy** — install from <https://www.mitmproxy.org/>

## Install

Open the folder where you want to store your config in a terminal. If you don't
already have a `package.json`, initialize it with

```sh
npm init --init-license=UNLICENSED -y
```

Then install and initialize `@hummingbirdworks/proxy`.

```sh
npm install -D @hummingbirdworks/proxy
npx hummingbird-proxy init
```

This creates a `proxy.config.toml` in the current directory and adds a `proxy`
script (`"proxy": "hummingbird-proxy"`) to your `package.json`.

## Run the proxy

Run the proxy from the folder containing `proxy.config.toml` (or pass a config
path and any extra `mitmdump` args):

```sh
npm run proxy
```

Then launch a browser through it:

```sh
msedge.exe --proxy-server="http://localhost:8080"
# OR
chrome.exe --proxy-server="http://localhost:8080"
```

### ⚠️ **Important**

- Chrome/Edge share one background process across windows. Close all
  Chrome/Edge windows first, or use a separate profile:
  `msedge.exe --user-data-dir="%LOCALAPPDATA%\mitmproxy-browser-profile" --proxy-server="http://localhost:8080"`
- Power Apps caches assets in the browser. If changes don't show, hard refresh
  (`Ctrl+Shift+R`); you may also need to bypass the service worker cache
  (DevTools → Application → Service Workers → "Bypass for network").

## Install cert (first run only)

Install the mitmproxy root certificate so HTTPS interception works: with the
proxied browser open, visit <http://mitm.it/> and follow the instructions.

## Configure

The config is a TOML file with a `rules` array-of-tables; each `[[rules]]` entry
is one redirect:

```toml
# Single web resource file -> local file
[[rules]]
type = "single"
web-resource-name = "test_/ribbonscript/opportunity.js"
local-path = "./src/webresources/ribbonscript/opportunity.js"

# Folder of web resources -> local folder
[[rules]]
type = "folder"
web-resource-folder = "test_/custom-app/"
local-path = "./src/webresources/custom-app"

# Folder of web resources -> local dev server (only for one host)
[[rules]]
type = "devserver"
web-resource-folder = "test_/bookings-editor/"
local-url = "http://localhost:5173"
domain = "myorg.crm.dynamics.com"

# PCF control -> local build output folder.
# Single-quoted literal strings keep Windows backslashes as-is.
[[rules]]
type = "pcf"
control = "test.BookingsEditor"
local-path = 'C:\Users\me\repo\bookings-editor\out\controls\BookingsEditor'
```

Optional keys on any rule:

- `domain`: a host string, or an array of host strings. Omit for all hosts.
- `disabled`: `true` to skip the rule.

### Combining several projects with `include`

To proxy several projects against the same environment from one running proxy,
`include` their configs instead of switching proxies as you navigate:

```toml
[[rules]]
type = "include"
path = "../invoice-editor/proxy.config.toml"

[[rules]]
type = "include"
# Use single quotes to support backslashes in absolute paths
path = 'C:\Users\me\repos\myproject\proxy.config.toml'
```

## Using with Vite (HMR)

A `devserver` rule routes a web resource's requests to a running Vite dev
server for hot module reload on the Dynamics-hosted page.

### Vite config

The package ships a Vite plugin that sets the base path, enables HMR through the
proxy, and disables cache busting (Power Apps already busts caches on publish).

```ts
import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { powerAppsWebResource } from '@hummingbirdworks/proxy/vite'

export default defineConfig({
  plugins: [
    svelte(), // or react(), vue(), etc.
    powerAppsWebResource({ prefix: 'test_/myapp/' }),
  ],
  server: { port: 5173 },
})
```

Options:

- `prefix` (required): the web resource path, e.g. `test_/myapp/`.
- `hmrClientPort` (default `443`): port the browser uses for the HMR socket.
- `stableFilenames` (default `true`): emit unhashed filenames and a single
  stylesheet. Set `false` to keep Vite's defaults.

If your HTML entry isn't `index.html`, add it to `build.rollupOptions.input`.

### Proxy rule

Point a `devserver` rule at the dev server. The `local-url` scheme/port must match
what Vite serves (`http://localhost:5173` by default here):

```toml
[[rules]]
type = "devserver"
web-resource-folder = "test_/myapp/"
local-url = "http://localhost:5173"
domain = "myorg.crm.dynamics.com"
```

### Run

Start the dev server and the proxy, then browse through the proxy:

```sh
npm run dev
npm run proxy
```

Open the Dynamics page hosting the web resource. Edit → save → the page updates
without a manual refresh. If HMR doesn't trigger, confirm Vite's port matches
the rule `local-url` and that the service worker cache is bypassed (see Notes above).

## Advanced

Configure use of a specific config file by name and/or set the proxy port by passing args.

```
npx hummingbird-proxy ./proxy.config.toml -p 8888
```