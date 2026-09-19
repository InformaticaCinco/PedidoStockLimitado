import { Component, inject, OnInit, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { finalize } from 'rxjs';
import { ProductosApiService } from '../core/api';
import { Product, Stock } from '../core/models';
import { WarehouseResolver } from '../core/order-flow';
import { errorMessage, Notifications } from '../core/errors';
import { UI } from '../shared/ui';

@Component({standalone:true,imports:[...UI,ReactiveFormsModule,MatDialogModule],template:`
<h2 mat-dialog-title>Stock de {{product.nombre}}</h2>
<form [formGroup]="form" (ngSubmit)="save()">
 <mat-dialog-content class="dialog-fields">
  <p class="muted">{{product.sku}} · Almacén {{warehouse}}</p>
  @if(loading()){<mat-progress-bar mode="indeterminate" aria-label="Consultando stock"/>}
  @if(stock();as current){
   <p>Reservado: {{current.reservado}} · Total: {{current.total}}</p>
   <mat-form-field appearance="outline"><mat-label>Stock disponible</mat-label><input matInput type="number" formControlName="disponible" min="0" max="1000000000" step="1"/><mat-error>Ingresa un entero entre 0 y 1000000000.</mat-error></mat-form-field>
   <p class="muted">El ajuste modifica solo el disponible; las unidades reservadas se conservan.</p>
  }
  @if(error()){<p class="feedback error" role="alert">{{error()}}</p>@if(!stock()){<button mat-button type="button" (click)="load()" [disabled]="loading()">Reintentar consulta</button>}}
 </mat-dialog-content>
 <mat-dialog-actions align="end"><button mat-button type="button" [disabled]="saving()" (click)="close()">Cancelar</button><button mat-flat-button color="primary" [disabled]="!stock()||form.invalid||loading()||saving()">{{saving()?'Guardando…':'Guardar stock'}}</button></mat-dialog-actions>
</form>`})
export class StockDialog implements OnInit {
 readonly product=inject<Product>(MAT_DIALOG_DATA);
 readonly warehouse=inject(WarehouseResolver).resolve(this.product);
 private api=inject(ProductosApiService);private ref=inject(MatDialogRef<StockDialog>);private notify=inject(Notifications);
 loading=signal(false);saving=signal(false);error=signal('');stock=signal<Stock|null>(null);
 form=inject(FormBuilder).nonNullable.group({disponible:[0,[Validators.required,Validators.min(0),Validators.max(1000000000),Validators.pattern(/^\d+$/)]]});
 ngOnInit(){this.load();}
 load(){if(this.loading())return;if(!this.warehouse){this.error.set('El producto no tiene un almacén disponible. Actualiza el catálogo.');return;}this.loading.set(true);this.error.set('');this.api.stock(this.product.sku,this.warehouse).pipe(finalize(()=>this.loading.set(false))).subscribe({next:s=>{this.stock.set(s);this.form.setValue({disponible:s.disponible});},error:e=>this.error.set(errorMessage(e))});}
 save(){if(!this.warehouse||!this.stock()||this.form.invalid||this.loading()||this.saving())return;this.saving.set(true);this.ref.disableClose=true;this.error.set('');this.api.updateStock(this.product.sku,this.warehouse,this.form.getRawValue().disponible).pipe(finalize(()=>{this.saving.set(false);this.ref.disableClose=false;})).subscribe({next:s=>{this.notify.show('Stock actualizado.','success');this.ref.close(s);},error:e=>this.error.set(errorMessage(e))});}
 close(){this.ref.close();}
}
