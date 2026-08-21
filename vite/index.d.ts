import type { Plugin } from "vite";

export interface WebResourceOptions {
  /** Web resource path prefix, e.g. `test_/myapp/`. Leading/trailing slashes are optional. */
  prefix: string;
  /** Port the browser uses for the HMR websocket. Defaults to `443`. */
  hmrClientPort?: number;
  /**
   * Emit unhashed filenames and a single stylesheet so solution components stay
   * stable across builds. Defaults to `true`; set `false` to keep Vite's defaults.
   */
  stableFilenames?: boolean;
}

/**
 * Vite plugin that aligns the dev server and build output with a Dataverse /
 * Dynamics 365 web resource served through `@hummingbirdworks/proxy`.
 *
 * Sets `base` (absolute in dev, relative in build) and a `wss` HMR socket, and
 * optionally emits stable filenames.
 */
export function powerAppsWebResource(options: WebResourceOptions): Plugin;
