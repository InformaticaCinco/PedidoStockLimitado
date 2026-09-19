import { chromium } from 'playwright';

const base = 'http://localhost:8080';

async function probar(usuario, rutaEsperada) {
  const browser = await chromium.launch({headless:true});
  const context = await browser.newContext();
  const page = await context.newPage();

  let remoteEntry = 0;

  page.on('request', req => {
    if (req.url().includes('remoteEntry.js')) remoteEntry++;
  });

  await page.goto(base, {waitUntil:'domcontentloaded'});

  const user = page.locator(
    'input[formcontrolname="usuario"],input[name="usuario"],input[type="text"]'
  ).first();

  const pass = page.locator(
    'input[formcontrolname="clave"],input[name="clave"],input[type="password"]'
  ).first();

  await user.fill(usuario);
  await pass.fill('Reto2026!');
  await pass.press('Enter');

  await page.waitForTimeout(1200);

  // Reiniciamos contador después del login.
  remoteEntry = 0;

  await page.goto(base + '/admin', {waitUntil:'domcontentloaded'});
  await page.waitForTimeout(1200);

  const url = page.url();

  await browser.close();

  if (url.includes('/admin')) {
    throw new Error(`${usuario}: logró permanecer en /admin`);
  }

  if (!url.includes(rutaEsperada)) {
    throw new Error(`${usuario}: redirección inesperada ${url}`);
  }

  if (remoteEntry !== 0) {
    throw new Error(
      `${usuario}: descargó remoteEntry.js ${remoteEntry} vez/veces`
    );
  }

  return {usuario,url,remoteEntry};
}

const comprador = await probar('comprador01','/comprador/');
const vendedor = await probar('vendedor01','/vendedor/');

console.log(JSON.stringify({comprador,vendedor}));
