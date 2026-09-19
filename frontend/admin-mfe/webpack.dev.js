const config = require('./webpack.config');
// CLI 17 injects development styles.js as a classic script: avoid import.meta
// in its auto publicPath. Production keeps automatic remote-origin resolution.
module.exports = { ...config, output: { ...config.output, publicPath: 'http://localhost:8081/' } };
