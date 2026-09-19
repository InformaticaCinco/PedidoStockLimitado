// Read-only integration server: serves the already-built host without ng serve
// writing caches/builds into web-host. All logs/evidence belong to admin-mfe.
import {createServer,request} from 'node:http';
import {readFile,stat} from 'node:fs/promises';
import {resolve,extname,sep} from 'node:path';
const root=resolve('../web-host/dist/web-host');await stat(resolve(root,'index.html'));
const upstreams={'/api/java':8090,'/api/despachos':8091,'/api/cargas':8092};
createServer(async(req,res)=>{
 const url=new URL(req.url,'http://localhost:8080');
 for(const [prefix,port] of Object.entries(upstreams))if(url.pathname.startsWith(prefix+'/')){
  const upstream=request({hostname:'127.0.0.1',port,path:url.pathname.slice(prefix.length)+url.search,method:req.method,headers:{...req.headers,host:'localhost:'+port}},r=>{res.writeHead(r.statusCode,r.headers);r.pipe(res);});
  upstream.on('error',()=>{if(!res.headersSent)res.writeHead(502,{'Content-Type':'application/json'});res.end(JSON.stringify({code:502,data:null,message:'Backend no disponible'}));});req.pipe(upstream);return;
 }
 try{
  let path=resolve(root,'.'+decodeURIComponent(url.pathname));if(path!==root&&!path.startsWith(root+sep)){res.writeHead(403);res.end();return;}
  if(!extname(path))path=resolve(root,'index.html');
  const body=await readFile(path);const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml'};
  res.writeHead(200,{'Content-Type':types[extname(path)]??'application/octet-stream','Cache-Control':'no-store'});res.end(body);
 }catch{res.writeHead(404);res.end('Not found');}
}).listen(8080,'127.0.0.1',()=>console.log('Host existente servido en http://localhost:8080; sin escrituras en web-host.'));
