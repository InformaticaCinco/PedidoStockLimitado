const fs = require('fs');
const chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
if (!process.env.CHROME_BIN && fs.existsSync(chrome)) process.env.CHROME_BIN = chrome;
module.exports = config => config.set({
  frameworks: ['jasmine', '@angular-devkit/build-angular'],
  plugins: [require('karma-jasmine'),require('karma-chrome-launcher'),require('karma-coverage'),require('@angular-devkit/build-angular/plugins/karma')],
  reporters: ['progress'], browsers: ['ChromeHeadlessLocal'],
  customLaunchers: { ChromeHeadlessLocal: { base: 'ChromeHeadless', flags: ['--no-sandbox','--disable-dev-shm-usage'] } },
  singleRun: true, browserNoActivityTimeout: 60000, client: { jasmine: { random: false } }
});
