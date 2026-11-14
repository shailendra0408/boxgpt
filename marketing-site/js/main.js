/* Shared on every page: Industries dropdown and mobile menu. */
"use strict";
(function(){
  const $=id=>document.getElementById(id);
  const ddb=$('ddb'),ddm=$('ddm');
  if(ddb&&ddm){
    ddb.addEventListener('click',e=>{e.stopPropagation();ddb.setAttribute('aria-expanded',ddm.classList.toggle('open'))});
    document.addEventListener('click',()=>{ddm.classList.remove('open');ddb.setAttribute('aria-expanded','false')});
  }
  const mn=$('mnav'),bg=$('burger');
  if(mn&&bg){
    const closeM=()=>{mn.hidden=true;bg.setAttribute('aria-expanded','false')};
    bg.addEventListener('click',e=>{e.stopPropagation();const o=mn.hidden;mn.hidden=!o;bg.setAttribute('aria-expanded',String(o))});
    mn.addEventListener('click',e=>{if(e.target.closest('a'))closeM()});
    addEventListener('hashchange',closeM);
    addEventListener('resize',()=>{if(innerWidth>900)closeM()});
    addEventListener('keydown',e=>{if(e.key==='Escape'){closeM();if(ddm){ddm.classList.remove('open');ddb.setAttribute('aria-expanded','false')}}});
  }
})();
