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

## Config reference (CLI / env)

- **Config path resolution:** the CLI uses the first non-flag argument as the
  config path, defaulting to `./proxy.config.toml` in the current directory. It
  passes the resolved absolute path to the addon via the
  `HUMMINGBIRD_PROXY_CONFIG` environment variable.
- **Running the addon directly** (without the CLI) is also supported:

  ```sh
  HUMMINGBIRD_PROXY_CONFIG=/abs/path/proxy.config.toml mitmdump -s powerapp_dev_proxy.py
  ```