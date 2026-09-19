import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { AdminRemoteService, REMOTE_LOADER } from './admin';
import { CONFIG } from '../core/config';
describe('Recuperación del remoto ESM',()=>{
 it('reintento invalida import fallido, conserva query y monta rutas una vez',async()=>{
  const loader=jasmine.createSpy('loader').and.returnValues(Promise.reject(Error('offline')),Promise.resolve({ADMIN_ROUTES:[{path:'',children:[]}]}));
  TestBed.configureTestingModule({providers:[provideRouter([{path:'',children:[{path:'admin',children:[]}]}]),{provide:REMOTE_LOADER,useValue:loader},{provide:CONFIG,useValue:{adminRemoteEntry:'http://localhost:8081/remoteEntry.js?v=1'}}]});
  const remote=TestBed.inject(AdminRemoteService);
  await expectAsync(remote.mount()).toBeRejected();await remote.mount();await remote.mount();
  expect(loader.calls.count()).toBe(2);
  expect(loader.calls.argsFor(0)[0]).toBe('http://localhost:8081/remoteEntry.js?v=1');
  expect(loader.calls.argsFor(1)[0]).toContain('v=1&mfRetry=');
  expect(TestBed.inject(Router).config[0].children?.[0].children?.length).toBe(1);
 });
});
