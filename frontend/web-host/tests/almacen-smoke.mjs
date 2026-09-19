import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
const browser=await chromium.launch({executablePath:process.env.CHROME_BIN||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
const evidence=[];
try {
 for(const [usuario,role,path] of [['comprador01','COMPRADOR','/comprador/catalogo'],['vendedor01','VENDEDOR','/vendedor/productos']]){
  const context=await browser.newContext({viewport:{width:1440,height:1000}});const page=await context.newPage();const failures=[];
  page.on('pageerror',e=>failures.push(e.message));
  await page.goto('http://127.0.0.1:8080/login');
  await page.getByLabel('Usuario',{exact:true}).fill(usuario);await page.getByLabel('Contraseña',{exact:true}).fill('Reto2026!');
  await page.getByRole('button',{name:'Ingresar',exact:true}).click();await page.waitForURL('**'+path);await page.locator('article.product').first().waitFor();
  const api=await page.evaluate(async()=>{
   const s=JSON.parse(sessionStorage.getItem('pedidos.session.v1'));const headers={Authorization:'Bearer '+s.accessToken};
   const r=await fetch('/api/java/productos?pagina=0',{headers});const products=(await r.json()).data;
   const own=products.filter(p=>p.vendedorId===s.usuario.id);
   const sample=(s.usuario.rol==='VENDEDOR'?own:products).find(p=>p.sku!=='SKU-00001');
   const sr=await fetch('/api/java/productos/'+sample.sku+'/stock?almacenId='+encodeURIComponent(sample.almacenId),{headers});
   const critical=products.find(p=>p.sku==='SKU-00001');
   const cr=await fetch('/api/java/productos/'+critical.sku+'/stock?almacenId='+encodeURIComponent(critical.almacenId),{headers});
   return {role:s.usuario.rol,catalogStatus:r.status,products,ownCount:own.length,sample,stockStatus:sr.status,stock:(await sr.json()).data,critical:(await cr.json()).data};
  });
  assert.equal(api.catalogStatus,200);assert(api.products.every(p=>/^ALM-\d{2}$/.test(p.almacenId)));
  assert.equal(api.stockStatus,200);assert.equal(api.stock.almacenId,api.sample.almacenId);
  assert.deepEqual([api.critical.disponible,api.critical.reservado,api.critical.total],[3,0,3]);
  if(role==='COMPRADOR'){
   const selected=api.sample;const other=api.products.find(p=>p.almacenId!==selected.almacenId);
   await page.locator('article.product').filter({hasText:selected.sku}).getByRole('button',{name:'Seleccionar',exact:true}).click();
   await page.getByRole('button',{name:'Confirmar pedido',exact:true}).waitFor();assert(await page.getByRole('button',{name:'Confirmar pedido',exact:true}).isEnabled());
   await page.locator('article.product').filter({hasText:other.sku}).getByRole('button',{name:'Seleccionar',exact:true}).click();
   await page.getByRole('alert').filter({hasText:'No puedes mezclar productos de almacenes diferentes'}).waitFor();
   assert.equal(await page.locator('.selection-row').count(),1);
   evidence.push({role,catalogStatus:200,products:api.products.length,allProductsHaveWarehouse:true,selectedSku:selected.sku,selectedWarehouse:selected.almacenId,createEnabled:true,mixedWarehousesBlocked:true,critical:api.critical});
  }else{
   assert(api.products.filter(p=>p.vendedorId===api.sample.vendedorId).every(p=>p.almacenId==='ALM-01'),'Fixture vendedor01 corresponde a ALM-01');
   await page.getByRole('button',{name:'Editar stock '+api.sample.sku,exact:true}).click();
   await page.getByRole('dialog').waitFor();await page.getByLabel('Stock disponible',{exact:true}).waitFor();
   assert.equal(Number(await page.getByLabel('Stock disponible',{exact:true}).inputValue()),api.stock.disponible);
   assert(await page.getByRole('button',{name:'Guardar stock',exact:true}).isEnabled());
   assert.equal(await page.getByRole('dialog').locator('input').count(),1);
   await page.getByRole('button',{name:'Cancelar',exact:true}).click();
   evidence.push({role,catalogStatus:200,ownProducts:api.ownCount,sku:api.sample.sku,warehouse:api.sample.almacenId,stockStatus:api.stockStatus,stock:api.stock,stockEditorEnabled:true,noManualWarehouse:true,critical:api.critical});
  }
  assert.deepEqual(failures,[]);
  await page.getByRole('button',{name:'Cerrar sesión'}).click();await page.waitForURL('**/login');await context.close();
 }
 const result={ok:true,evidence,noOrderSubmitted:true,noStockWritten:true,tokensOmitted:true};
 await writeFile('.build/almacen-smoke.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
} finally {await browser.close();}
