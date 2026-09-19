import('./bootstrap').catch(() => {
  document.body.textContent = 'No se pudo iniciar la aplicación. Recarga la página para reintentar.';
});
