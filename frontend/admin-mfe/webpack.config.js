const { withModuleFederationPlugin, share } = require('@angular-architects/module-federation/webpack');
module.exports = withModuleFederationPlugin({
  name: 'adminMfe', filename: 'remoteEntry.js',
  exposes: { './Routes': './src/app/admin.routes.ts' },
  shared: share({
    '@angular/core': { singleton: true, strictVersion: true, requiredVersion: 'auto' },
    '@angular/common': { singleton: true, strictVersion: true, requiredVersion: 'auto', includeSecondaries: true },
    '@angular/router': { singleton: true, strictVersion: true, requiredVersion: 'auto' },
    '@angular/forms': { singleton: true, strictVersion: true, requiredVersion: 'auto' },
    'rxjs': { singleton: true, strictVersion: true, requiredVersion: 'auto' }
  })
});
