// AI IPO Watch: tiny progressive enhancements (sorting, live countdowns, placeholder newsletter form)
(function(){
  // sortable tables: click a header to sort; uses data-v when present
  document.querySelectorAll('table.sortable').forEach(function(t){
    t.querySelectorAll('th').forEach(function(th,i){
      th.addEventListener('click',function(){
        var tb=t.tBodies[0],rows=[].slice.call(tb.rows),asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
        rows.sort(function(a,b){
          var x=a.cells[i],y=b.cells[i];if(!x||!y)return 0;
          var vx=x.dataset.v!==undefined?x.dataset.v:x.innerText.trim(),vy=y.dataset.v!==undefined?y.dataset.v:y.innerText.trim();
          var nx=parseFloat(vx),ny=parseFloat(vy);
          if(vx===''&&vy!=='')return 1;if(vy===''&&vx!=='')return -1;
          var r=(!isNaN(nx)&&!isNaN(ny)&&/^[-\d.]+$/.test(vx)&&/^[-\d.]+$/.test(vy))?nx-ny:String(vx).localeCompare(String(vy));
          return asc?r:-r;});
        rows.forEach(function(r){tb.appendChild(r)});
      });
    });
  });
  // live countdowns (build-time value is correct on build day; refresh client-side)
  var today=new Date();today.setHours(0,0,0,0);
  document.querySelectorAll('.cd[data-date]').forEach(function(el){
    var p=el.dataset.date.split('-'),dt=new Date(+p[0],p[1]-1,+p[2]);var n=Math.round((dt-today)/864e5);
    el.textContent=n>0?n+' days':n===0?'today':'passed';
  });
  // newsletter placeholder: don't submit anywhere until an action URL is configured
  document.querySelectorAll('form.nl').forEach(function(f){
    f.addEventListener('submit',function(ev){
      if(f.dataset.placeholder==='1'){ev.preventDefault();f.querySelector('.nl-msg').textContent='Thanks! Signup is not live yet. This form is a placeholder (nothing was sent).';}
    });
  });
  // affiliate placeholders: block navigation to '#'
  document.querySelectorAll('a[data-affiliate]').forEach(function(a){
    if(a.getAttribute('href')==='#')a.addEventListener('click',function(ev){ev.preventDefault();alert('Partner link placeholder: not active yet.');});
  });
})();
