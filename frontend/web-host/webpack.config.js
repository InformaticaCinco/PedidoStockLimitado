const { withModuleFederationPlugin, share } = require('@angular-architects/module-federation/webpack');
module.exports = withModuleFederationPlugin({
  name: 'webHost',
  remotes: {}, // Dynamic remote: never fetched at startup or preloaded.
  shared: share({
    '@angular/core': { singleton: true, strictVersion: true, requiredVersion: 'auto' },
    '@angular/common': { singleton: true, strictVersion: true, requiredVersion: 'auto', includeSecondaries: true },
    '@angular/router': { singleton: true, strictVersion: true, requiredVersion: 'auto' },
    '@angular/forms': { singleton: true, strictVersion: true, requiredVersion: 'auto' },
    'rxjs': { singleton: true, strictVersion: true, requiredVersion: 'auto' }
  })
});

// Host is served at origin root. CLI 17 injects dev styles.js as a classic script;
// an explicit path avoids webpack's import.meta-based auto publicPath in it.
module.exports.output.publicPath = '/';
