import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
await mkdir('.build',{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROME_BIN||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
const results=[];
try {
 for(const [login,role,home] of [['comprador01','COMPRADOR','/comprador/catalogo'],['vendedor01','VENDEDOR','/vendedor/productos'],['admin','ADMIN','/admin']]){
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const page=await context.newPage();const remotes=[];const failures=[];
  page.on('request',r=>{if(r.url().includes('remoteEntry'))remotes.push(r.url());});
  page.on('pageerror',e=>failures.push(e.message));
  await page.goto('http://127.0.0.1:8080/login');
  await page.getByLabel('Usuario',{exact:true}).fill(login);
  await page.getByLabel('Contraseña',{exact:true}).fill('Reto2026!');
  await page.getByRole('button',{name:'Ingresar',exact:true}).click();
  await page.waitForURL('**'+home);
  if(role==='ADMIN'){
   await page.getByRole('heading',{name:'Módulo de administración no disponible'}).waitFor();
   assert(remotes.length>0,'ADMIN intenta cargar remoto');
   const before=remotes.length;await page.getByRole('button',{name:'Reintentar',exact:true}).click();
   await page.getByRole('heading',{name:'Módulo de administración no disponible'}).waitFor();
   assert(remotes.length>before,'Reintento vuelve a solicitar remoteEntry');
   results.push({role,fallback:true,remoteAttempts:remotes.length});
  }else{
   await page.locator('article.product').first().waitFor();
   const products=await page.locator('article.product').count();assert(products>0);
   await page.screenshot({path:`.build/${role.toLowerCase()}-desktop.png`,fullPage:false,animations:'disabled'});
   await page.reload();await page.locator('article.product').first().waitFor();
   assert.equal(await page.locator('article.product').count(),products,'Sesión restaurada');
   // An explicit forbidden route must not even request the remote.
   await page.goto('http://127.0.0.1:8080/admin');await page.waitForURL('**'+home);
   await page.locator('article.product').first().waitFor();
   assert.equal(remotes.length,0,'No se descarga ADMIN');
   const api=await page.evaluate(async()=>{
    const session=JSON.parse(sessionStorage.getItem('pedidos.session.v1'));
    const headers={Authorization:'Bearer '+session.accessToken};
    const catalog=await fetch('/api/java/productos?pagina=0',{headers});
    const data=(await catalog.json()).data;
    const orders=await fetch('/api/java/pedidos?pagina=0',{headers});
    const orderData=(await orders.json()).data;
    const stock=await fetch('/api/java/productos/SKU-00001/stock?almacenId=ALM-01',{headers});
    const stockData=(await stock.json()).data;
    return {catalogStatus:catalog.status,catalogCount:data.length,ownCount:data.filter(p=>p.vendedorId===session.usuario.id).length,ordersStatus:orders.status,ordersCount:orderData.length,stockStatus:stock.status,stock:stockData};
   });
   assert.equal(api.catalogStatus,200);assert.equal(api.ordersStatus,200);assert.equal(api.stockStatus,200);
   assert.deepEqual([api.stock.disponible,api.stock.reservado,api.stock.total],[3,0,3]);
   if(role==='VENDEDOR')assert.equal(products,api.ownCount);
   if(role==='COMPRADOR'){
    await page.getByRole('button',{name:'Seleccionar',exact:true}).first().click();
    assert(await page.getByRole('button',{name:'Confirmar pedido',exact:true}).isEnabled(),'Usa el almacén real para habilitar pedido');
   }else{
    await page.getByRole('button',{name:'Nuevo producto'}).click();
    await page.getByRole('dialog').waitFor();assert(await page.getByRole('button',{name:'Guardar producto'}).isDisabled());
    await page.getByRole('button',{name:'Cancelar',exact:true}).click();
   }
   await page.getByRole('link',{name:role==='COMPRADOR'?'Mis pedidos':'Pedidos recibidos',exact:true}).click();
   await page.getByRole('heading',{name:role==='COMPRADOR'?'Mis pedidos':'Pedidos recibidos',exact:true}).waitFor();
   await page.getByRole('heading',{name:'Todavía no hay pedidos',exact:true}).waitFor();
   await page.setViewportSize({width:390,height:844});
   await page.getByRole('button',{name:'Abrir menú'}).click();
   await page.getByRole('link',{name:role==='COMPRADOR'?'Catálogo':'Productos',exact:true}).click();
   await page.locator('article.product').first().waitFor();
   await page.locator('.mat-drawer-backdrop').waitFor({state:'hidden'});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'Sin overflow horizontal móvil');
   await page.screenshot({path:`.build/${role.toLowerCase()}-mobile.png`,fullPage:false,animations:'disabled'});
   results.push({role,productsRendered:products,sessionRestore:true,forbiddenAdminRedirect:true,remoteRequests:remotes.length,mobileWidth:390,noHorizontalOverflow:true,...api});
  }
  assert.deepEqual(failures,[],'Sin errores JS no controlados');
  await page.getByRole('button',{name:'Cerrar sesión'}).click();await page.waitForURL('**/login');
  assert.equal(await page.evaluate(()=>sessionStorage.getItem('pedidos.session.v1')),null);
  await context.close();
 }
 await writeFile('.build/smoke.json',JSON.stringify({ok:true,results,noOrdersCreated:true,noProductsMutated:true,tokensOmitted:true},null,2));
 console.log(JSON.stringify({ok:true,results,tokensOmitted:true},null,2));
}finally{await browser.close();}
