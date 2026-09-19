import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { finalize } from 'rxjs';
import { ProductosApiService } from '../core/api';
import { Product } from '../core/models';
import { errorMessage, Notifications } from '../core/errors';
import { UI } from '../shared/ui';
@Component({standalone:true,imports:[...UI,ReactiveFormsModule,MatDialogModule],template:`
<h2 mat-dialog-title>{{product?'Editar producto':'Nuevo producto'}}</h2><form [formGroup]="form" (ngSubmit)="save()"><mat-dialog-content class="dialog-fields"><p class="muted">Completa la información de tu producto.</p><mat-form-field appearance="outline"><mat-label>SKU</mat-label><input matInput formControlName="sku" placeholder="SKU-00042" maxlength="9"/><mat-error>Usa SKU- y cinco dígitos.</mat-error></mat-form-field><mat-form-field appearance="outline"><mat-label>Nombre</mat-label><input matInput formControlName="nombre" maxlength="120"/><mat-error>Ingresa un nombre de hasta 120 caracteres.</mat-error></mat-form-field><div class="form-row"><mat-form-field appearance="outline"><mat-label>Precio</mat-label><input matInput type="number" formControlName="precio" min="0.01" max="999999999.99" step="0.01"/><mat-error>Precio positivo, hasta 999999999.99.</mat-error></mat-form-field><mat-form-field appearance="outline"><mat-label>Peso (kg)</mat-label><input matInput type="number" formControlName="peso" min="0.000001" max="100000" step="0.000001"/><mat-error>Hasta 100000 kg y 6 decimales.</mat-error></mat-form-field></div>@if(error()){<p class="feedback error" role="alert">{{error()}}</p>}</mat-dialog-content><mat-dialog-actions align="end"><button mat-button type="button" [disabled]="busy()" (click)="close()">Cancelar</button><button mat-flat-button color="primary" [disabled]="form.invalid||busy()">{{busy()?'Guardando…':'Guardar producto'}}</button></mat-dialog-actions></form>`})
export class ProductDialog {
 readonly product=inject<Product|null>(MAT_DIALOG_DATA);private ref=inject(MatDialogRef<ProductDialog>);private api=inject(ProductosApiService);private notify=inject(Notifications);private fb=inject(FormBuilder);
 busy=signal(false);error=signal('');
 form=this.fb.nonNullable.group({sku:[{value:this.product?.sku??'',disabled:!!this.product},[Validators.required,Validators.pattern(/^SKU-\d{5}$/)]],nombre:[this.product?.nombre??'',[Validators.required,Validators.maxLength(120),Validators.pattern(/\S/)]],precio:[this.product?.precio??0,[Validators.required,Validators.min(.01),Validators.max(999999999.99)]],peso:[this.product?.peso??0,[Validators.required,Validators.min(.000001),Validators.max(100000),Validators.pattern(/^\d+(\.\d{1,6})?$/)]]});
 close(){this.ref.close(false);}
 save(){if(this.form.invalid||this.busy())return;this.busy.set(true);this.ref.disableClose=true;this.error.set('');const p=this.form.getRawValue();(this.product?this.api.update(this.product.sku,p):this.api.create(p)).pipe(finalize(()=>{this.busy.set(false);this.ref.disableClose=false;})).subscribe({next:()=>{this.notify.show('Producto guardado.','success');this.ref.close(true);},error:e=>this.error.set(errorMessage(e))});}
}
