import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
const results={admin:{},isolation:[],mutations:[],pageErrors:[]};
try {
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();const remote=[];const api=[];
 page.on('pageerror',e=>results.pageErrors.push(e.message));
 page.on('response',r=>{if(r.url().includes('remoteEntry.js'))remote.push({url:r.url(),status:r.status()});if(r.url().includes('/api/')){const request=r.request();api.push({path:new URL(r.url()).pathname,status:r.status(),method:request.method(),bearer:!!request.headers()['authorization'],correlation:!!request.headers()['x-correlation-id']});}});
 await page.goto('http://localhost:8080/login');assert.equal(remote.length,0);
 await page.getByLabel('Usuario',{exact:true}).fill('admin');await page.getByLabel('Contraseña',{exact:true}).fill('Reto2026!');await page.getByRole('button',{name:'Ingresar',exact:true}).click();
 await page.waitForURL('**/admin/dashboard',{timeout:30000});await page.getByRole('heading',{name:'Dashboard',exact:true}).waitFor();
 await page.getByRole('heading',{name:'No hay pedidos para mostrar',exact:true}).waitFor();
 assert.equal(await page.getByText('Módulo de administración no disponible').count(),0);
 assert(remote.some(r=>r.status===200&&new URL(r.url).port==='8081'));
 const nav=page.getByRole('navigation',{name:'Secciones de administración'});
 await nav.getByRole('link',{name:'Carga masiva'}).click();await page.waitForURL('**/admin/cargas');
 await page.locator('input[type=file]').setInputFiles({name:'seleccion-smoke.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:Buffer.from('Solo selección UI; no se sube al backend')});
 assert(await page.getByRole('button',{name:'Procesar archivo',exact:true}).isEnabled());
 await page.screenshot({path:'.build/admin-cargas-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:'.build/admin-cargas-mobile.png',fullPage:true});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
 await page.setViewportSize({width:1440,height:1000});
 await nav.getByRole('link',{name:'Revisión',exact:true}).click();await page.waitForURL('**/admin/revision');await page.getByRole('heading',{name:'No hay pedidos en revisión'}).waitFor();
 await nav.getByRole('link',{name:'Dashboard',exact:true}).click();await page.waitForURL('**/admin/dashboard');await page.getByRole('heading',{name:'No hay pedidos para mostrar',exact:true}).waitFor();
 const orders=api.filter(r=>r.path==='/api/java/pedidos');assert(orders.length>=2);assert(orders.every(r=>r.status===200&&r.bearer&&r.correlation));
 assert(!api.some(r=>r.method==='POST'&&!r.path.endsWith('/auth/login')));
 results.admin={login:true,remote,routes:['/admin/dashboard','/admin/cargas','/admin/revision'],ordersRequests:orders,fileSelection:true,uploadExecuted:false,mobileNoOverflow:true};
 await context.close();
 for(const [user,route] of [['comprador01','comprador'],['vendedor01','vendedor']]) {
  const c=await browser.newContext();const p=await c.newPage();let remoteCount=0;
  p.on('request',r=>{if(r.url().includes('remoteEntry.js'))remoteCount++;});
  await p.goto('http://localhost:8080/login');await p.getByLabel('Usuario',{exact:true}).fill(user);await p.getByLabel('Contraseña',{exact:true}).fill('Reto2026!');await p.getByRole('button',{name:'Ingresar',exact:true}).click();
  await p.waitForURL(`**/${route}/**`,{timeout:15000});await p.waitForLoadState('networkidle');assert.equal(remoteCount,0);results.isolation.push({user,remoteRequests:remoteCount});await c.close();
 }
 assert.deepEqual(results.pageErrors,[]);
 console.log(JSON.stringify(results,null,2));await writeFile('.build/smoke-results.json',JSON.stringify(results,null,2));
} finally {await browser.close();}
