# @hummingbirdworks/proxy

A [mitmproxy](https://www.mitmproxy.org/)-based dev proxy that redirects
Dataverse / Dynamics 365 **web resources** and **PCF control** assets to your
local dev builds or a running dev server (e.g. Vite). This lets you iterate on
web resources and PCF controls locally without deploying to the environment on
every change.

## How it works

The package ships a Python mitmproxy addon plus a small Node CLI
(`hummingbird-proxy`) that launches `mitmdump` with the addon and points it at
your config file. Redirect rules live in a `proxy.config.toml` file that you
check into your own repo. **All relative paths in the config are resolved
relative to the config file**, so the config is portable across machines.

## Prerequisites

- **Node.js** >= 16 (to run the CLI).
- **mitmproxy** installed and `mitmdump` available on your `PATH`
  (Python 3.11+, for stdlib TOML support).
  Install from <https://www.mitmproxy.org/> — e.g. `pipx install mitmproxy`.

## Install

```sh
npm install -D @hummingbirdworks/proxy
```

## Configure

Create a config in your repo with the `init` command:

```sh
npx hummingbird-proxy init
```

This copies the bundled example to `./proxy.config.toml` and adds a `proxy`
script (`"proxy": "hummingbird-proxy"`) to your `package.json`. Pass `--force`
to overwrite an existing config/script. (You can also copy the example manually
from `node_modules/@hummingbirdworks/proxy/proxy.config.example.toml`.)

The config is a TOML file. It's a table with a `rules` array-of-tables; each
`[[rules]]` entry is one redirect:

```toml
# Single web resource file -> local file
[[rules]]
type = "single"
name = "test_/ribbonscript/opportunity.js"
file = "./src/webresources/ribbonscript/opportunity.js"

# Folder of web resources -> local folder
[[rules]]
type = "folder"
name = "test_/custom-app/"
folder = "./src/webresources/custom-app"

# Folder of web resources -> local dev server (only for one host)
[[rules]]
type = "devserver"
name = "test_/bookings-editor/"
url = "https://localhost:5173"
domain = "myorg.crm.dynamics.com"

# PCF control -> local build output folder.
# Single-quoted literal strings keep Windows backslashes as-is.
[[rules]]
type = "pcf"
name = "test.BookingsEditor"
folder = 'C:\Users\me\repo\bookings-editor\out\controls\BookingsEditor'
```

Optional keys on any rule:

- `domain`: a host string, or an array of host strings. Omit for all hosts.
- `disabled`: `true` to skip the rule.

## Usage

Run the proxy from the folder containing `proxy.config.toml`:

```sh
npm run proxy
# or, without the added script:
npx hummingbird-proxy
```

Or point it at a specific config file:

```sh
npx hummingbird-proxy ./config/proxy.config.toml
```

Any extra arguments are forwarded to `mitmdump` (e.g. change the port):

```sh
npx hummingbird-proxy ./proxy.config.toml -p 8888
```

Then launch a browser through the proxy:

```sh
msedge.exe --proxy-server="http://localhost:8080"
# or
chrome.exe --proxy-server="http://localhost:8080"
```

### First-time setup

On first use, install the mitmproxy root certificate so HTTPS interception
works: with the proxied browser open, visit <http://mitm.it/> and follow the
instructions for your OS/browser.

### Notes

- Chrome and Edge share a single background process across all windows. Either
  close all Chrome/Edge windows before starting the proxy, or use a separate
  profile for the proxied browser:

  ```sh
  msedge.exe --user-data-dir="%LOCALAPPDATA%\mitmproxy-browser-profile" --proxy-server="http://localhost:8080"
  ```

- Power Apps caches web resources and PCF controls in the browser. If changes
  don't show up, force a full refresh (`Ctrl+Shift+R`). You may also need to
  open DevTools → Application → Service Workers and check "Bypass for network"
  to disable the service worker cache.

## Using with Vite (HMR)

A `devserver` rule routes a web resource's requests to a running Vite dev
server, giving you hot module reload on the Dynamics-hosted page.

The dev server can stay on plain HTTP — the browser only talks to the proxy, and
the proxy relays requests (including the HMR websocket) to `localhost`. Because
the Dynamics page is HTTPS, the browser would block an insecure `ws://` HMR
socket as mixed content, so point the HMR client at `wss` and let the proxy
forward it to the HTTP dev server. No dev-server cert (or `vite-plugin-mkcert`)
is needed.

### Vite config

The package ships a Vite plugin that helps with the configuration of web resources. 
It sets the base path, configures settings to support HMR with the proxy, and turns
off cache busting since powerapps already has cache busting when you publish customizations.

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

Point a `devserver` rule at the dev server. The `url` scheme/port must match
what Vite serves (`http://localhost:5173` by default here):

```toml
[[rules]]
type = "devserver"
name = "test_/myapp/"
url = "http://localhost:5173"
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
the rule `url`, that the HMR socket connects over `wss`, and that the service
worker cache is bypassed (see Notes above).
