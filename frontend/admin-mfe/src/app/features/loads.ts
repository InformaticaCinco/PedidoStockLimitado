import { Component, DestroyRef, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize, Subscription } from 'rxjs';
import { AdminCargasApiService } from '../core/api';
import { ADMIN_CONFIG } from '../core/config';
import { Carga } from '../core/models';
import { AdminFeedback, errorMessage, FileDownloader, progressOf, reportFilename, validateFile } from '../core/presentation';
import { RecentLoadsService } from '../core/recent-loads';
import { UI } from '../shared/ui';
import { AdminStatus } from '../shared/status';
@Component({standalone:true,imports:[...UI,AdminStatus],template:`
<div class="adm-heading"><div><p class="adm-eyebrow">IMPORTACIÓN DE PEDIDOS</p><h1>Carga masiva</h1><p class="adm-muted">Sube un archivo Excel y consulta el resultado de su procesamiento.</p></div></div>
<section class="adm-upload" [class.adm-dragging]="dragging()" (dragover)="drag($event)" (dragleave)="dragging.set(false)" (drop)="drop($event)">
 <span class="adm-empty-icon"><lucide-icon name="file-spreadsheet" size="32"/></span><h2>Arrastra tu archivo aquí</h2><p class="adm-muted">Formato .xlsx · Máximo {{maxBytes/1024/1024}} MiB</p>
 <input #picker type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden (change)="choose($event)" [disabled]="uploading()"/>
 <button mat-stroked-button color="primary" (click)="picker.click()" [disabled]="uploading()"><lucide-icon name="upload" size="18"/> Seleccionar archivo</button>
</section>
@if(file();as selected){<div class="adm-file"><lucide-icon name="file-spreadsheet"/><div><strong>{{selected.name}}</strong><p class="adm-muted">{{selected.size/1024|number:'1.1-1'}} KiB · {{uploading()?'Enviando':'Seleccionado'}}</p></div><button mat-button [disabled]="uploading()" (click)="clearFile();picker.value=''">Quitar</button></div>}
@if(fileError()){<p class="adm-feedback adm-danger" role="alert">{{fileError()}}</p>}
<div class="adm-upload-actions"><button mat-flat-button color="primary" [disabled]="!file()||!!fileError()||uploading()" (click)="upload()">{{uploading()?'Enviando archivo…':'Procesar archivo'}}</button><span class="adm-muted">Las filas se validan en el servidor. El archivo no se procesa en tu navegador.</span></div>
@if(uploading()){<mat-progress-bar mode="indeterminate" aria-label="Subiendo archivo"/>}
<section class="adm-recent"><div class="adm-heading"><div><h2>Cargas recientes de esta sesión</h2><p class="adm-muted">Solo las iniciadas desde este navegador. Máximo 10 referencias.</p></div></div>
@if(!recent.ids().length){<div class="adm-empty"><lucide-icon name="files" size="30"/><h3>Aún no hay cargas en esta sesión</h3><p>Después de subir un archivo podrás consultar aquí su estado y reporte.</p></div>}
@for(id of recent.ids();track id){<article class="adm-load-card"><div class="adm-heading"><h3 class="adm-id">{{id}}</h3><button mat-icon-button (click)="follow(id)" [attr.aria-label]="'Actualizar carga '+id"><lucide-icon name="refresh-cw" size="18"/></button></div>
@if(errors()[id]){<p class="adm-feedback adm-danger" role="alert">{{errors()[id]}}</p><button mat-button (click)="follow(id)">Reintentar seguimiento</button>}
@if(loads()[id];as c){<div aria-live="polite"><admin-status [state]="c.estado"/></div><dl class="adm-load-counts"><div><dt>Filas</dt><dd>{{c.totales.filas}}</dd></div><div class="adm-success-text"><dt>Aceptadas</dt><dd>{{c.totales.aceptadas}}</dd></div><div class="adm-danger-text"><dt>Rechazadas</dt><dd>{{c.totales.rechazadas}}</dd></div><div class="adm-warning-text"><dt>Duplicadas</dt><dd>{{c.totales.duplicadas}}</dd></div></dl>
@if(c.estado==='PROCESANDO'){@if(progress(c)!==null){<mat-progress-bar mode="determinate" [value]="progress(c)??0" aria-label="Filas procesadas"/><p class="adm-muted">{{progress(c)}}% de filas procesadas</p>}@else{<mat-progress-bar mode="indeterminate" aria-label="Analizando archivo"/><p class="adm-muted">Preparando el archivo; aún no se conoce el total de filas.</p>}}
@if(c.estado==='ERROR'){<p class="adm-feedback adm-danger">El procesamiento terminó con error. Revisa el archivo antes de iniciar una nueva carga.</p>}
@if(c.estado==='PROCESADA' && c.reporte){<button mat-stroked-button color="primary" [disabled]="downloading()[id]" (click)="download(c)"><lucide-icon name="download" size="18"/>{{downloading()[id]?'Descargando…':'Descargar reporte XLSX'}}</button>}
}@else if(!errors()[id]){<mat-progress-bar mode="indeterminate" aria-label="Consultando carga"/>}
</article>}
<p class="adm-muted">El detalle fila por fila está disponible en el reporte XLSX.</p></section>
`})
export class LoadsComponent implements OnInit,OnDestroy {
 private api=inject(AdminCargasApiService);private feedback=inject(AdminFeedback);private downloader=inject(FileDownloader);private destroy=inject(DestroyRef);
 readonly recent=inject(RecentLoadsService);readonly maxBytes=inject(ADMIN_CONFIG).maxUploadBytes;
 file=signal<File|null>(null);fileError=signal('');uploading=signal(false);dragging=signal(false);loads=signal<Record<string,Carga>>({});errors=signal<Record<string,string>>({});downloading=signal<Record<string,boolean>>({});private watchers=new Map<string,Subscription>();progress=progressOf;
 ngOnInit(){for(const id of this.recent.ids())this.follow(id);}
 choose(event:Event){const input=event.target as HTMLInputElement;this.select(input.files?.[0]??null);input.value='';}
 select(file:File|null){if(this.uploading())return;this.file.set(file);this.fileError.set(validateFile(file,this.maxBytes)??'');}
 clearFile(){this.file.set(null);this.fileError.set('');}
 drag(e:DragEvent){e.preventDefault();if(!this.uploading())this.dragging.set(true);}
 drop(e:DragEvent){e.preventDefault();this.dragging.set(false);if(this.uploading())return;const files=e.dataTransfer?.files;if(files?.length!==1){this.file.set(null);this.fileError.set('Selecciona un solo archivo XLSX.');return;}this.select(files[0]);}
 upload(){const file=this.file();if(this.uploading())return;const error=validateFile(file,this.maxBytes);if(error||!file){this.fileError.set(error??'Selecciona un archivo.');return;}this.uploading.set(true);this.fileError.set('');this.api.upload(file).pipe(takeUntilDestroyed(this.destroy),finalize(()=>this.uploading.set(false))).subscribe({next:r=>{this.recent.add(r.cargaId);for(const [id,sub] of this.watchers)if(!this.recent.ids().includes(id)){sub.unsubscribe();this.watchers.delete(id);}this.clearFile();this.follow(r.cargaId);this.feedback.show('Archivo recibido. El procesamiento continuará en el servidor.');},error:e=>this.fileError.set(errorMessage(e))});}
 follow(id:string){this.watchers.get(id)?.unsubscribe();this.errors.update(m=>({...m,[id]:''}));this.watchers.set(id,this.api.watch(id).pipe(takeUntilDestroyed(this.destroy)).subscribe({next:c=>this.loads.update(m=>({...m,[id]:c})),error:e=>this.errors.update(m=>({...m,[id]:errorMessage(e)}))}));}
 download(c:Carga){if(c.estado!=='PROCESADA'||!c.reporte||this.downloading()[c.cargaId])return;this.downloading.update(m=>({...m,[c.cargaId]:true}));this.api.report(c.cargaId).pipe(takeUntilDestroyed(this.destroy),finalize(()=>this.downloading.update(m=>({...m,[c.cargaId]:false})))).subscribe({next:r=>{if(!r.body){this.feedback.show('El reporte no contiene datos.',true);return;}this.downloader.save(r.body,reportFilename(r.headers.get('Content-Disposition'),c.cargaId));},error:e=>this.feedback.show(errorMessage(e),true)});}
 ngOnDestroy(){for(const sub of this.watchers.values())sub.unsubscribe();}
}
