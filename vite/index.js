"use strict";

// Vite plugin that configures a project so its dev server and build output line
// up with a Dataverse / Dynamics 365 web resource served through the proxy.

function powerAppsWebResource(options) {
  if (!options || typeof options.prefix !== "string") {
    throw new Error(
      "powerAppsWebResource: 'prefix' is required, e.g. 'test_/myapp/'."
    );
  }
  const prefix = options.prefix.replace(/^\/+|\/+$/g, "");
  if (!prefix) {
    throw new Error(
      "powerAppsWebResource: 'prefix' must not be empty, e.g. 'test_/myapp/'."
    );
  }
  const clientPort = options.hmrClientPort != null ? options.hmrClientPort : 443;
  const stableFilenames = options.stableFilenames !== false;

  return {
    name: "@hummingbirdworks/proxy:webresource",
    config(_config, env) {
      const isServe = env.command === "serve";
      // Dynamics pages are HTTPS, so the HMR socket must be wss to avoid
      // mixed-content blocking; the proxy relays it to the HTTP dev server.
      const config = {
        base: isServe ? "/webresources/" + prefix + "/" : "./",
        server: { hmr: { protocol: "wss", clientPort: clientPort } },
      };
      if (stableFilenames) {
        config.build = {
          cssCodeSplit: false,
          rollupOptions: {
            output: {
              // Stable filenames — Dynamics does its own cache busting on publish.
              entryFileNames: "[name].js",
              chunkFileNames: "[name].js",
              assetFileNames: "[name].[ext]",
            },
          },
        };
      }
      return config;
    },
  };
}

exports.powerAppsWebResource = powerAppsWebResource;
