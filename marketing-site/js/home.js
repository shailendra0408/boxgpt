/* Home page: animated question -> SQL -> answer demo in the hero. */
"use strict";
const $=id=>document.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
const esc=s=>s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const hl=s=>esc(s).replace(/\b(SELECT|FROM|WHERE|AND|ORDER BY|GROUP BY|DESC|LIMIT|SUM|AS|INTERVAL|DAY|COUNT|HAVING)\b/g,'<b>$1</b>');
const EX=[
{tab:'Banking',q:'Clients in the Lucknow region with a monthly average balance above ₹5 lakh',
 sql:['SELECT name, branch, avg_monthly_balance','FROM clients',"WHERE region = 'Lucknow'",'  AND avg_monthly_balance > 500000','ORDER BY avg_monthly_balance DESC;'],
 h:['Client','Branch','Avg. balance'],r:[['Sample client A','Hazratganj','₹ 9,42,000'],['Sample client B','Gomti Nagar','₹ 7,18,500'],['Sample client C','Aliganj','₹ 5,60,200']]},
{tab:'Insurance',q:'Policies in Lucknow that expire in the next 30 days',
 sql:['SELECT policy_no, holder, expiry_date','FROM policies',"WHERE city = 'Lucknow'",'  AND expiry_date <= CURDATE() + INTERVAL 30 DAY','ORDER BY expiry_date;'],
 h:['Policy','Holder','Expires'],r:[['P-10482','Sample holder A','18 Oct'],['P-10517','Sample holder B','24 Oct'],['P-10633','Sample holder C','06 Nov']]},
{tab:'Retail',q:'Top 3 outlets by sales last month in Uttar Pradesh',
 sql:['SELECT outlet, SUM(amount) AS sales','FROM orders',"WHERE state = 'Uttar Pradesh'",'  AND month = LAST_MONTH','GROUP BY outlet ORDER BY sales DESC LIMIT 3;'],
 h:['Outlet','City','Sales'],r:[['Outlet A','Lucknow','₹ 48,20,000'],['Outlet B','Kanpur','₹ 41,75,000'],['Outlet C','Varanasi','₹ 37,10,000']]},
{tab:'Manufacturing',q:'Which machines on Line 2 had more than 3 breakdowns last month?',
 sql:['SELECT machine, COUNT(*) AS breakdowns','FROM downtime_log',"WHERE line = 'Line 2'",'  AND month = LAST_MONTH','GROUP BY machine HAVING COUNT(*) > 3;'],
 h:['Machine','Line','Breakdowns'],r:[['Press-04','Line 2','5'],['Kiln motor K-12','Line 2','4'],['Conveyor C-07','Line 2','4']]}
];
const still=matchMedia('(prefers-reduced-motion:reduce)').matches;let tok=0,cur=0;
$('chips').innerHTML=EX.map((e,i)=>`<button data-i="${i}" aria-pressed="false">${e.tab}</button>`).join('');
$('chips').onclick=e=>{const b=e.target.closest('button');if(b)run(+b.dataset.i)};
async function run(i){
  const t=++tok,e=EX[i];cur=i;
  document.querySelectorAll('#chips button').forEach((b,k)=>b.setAttribute('aria-pressed',k===i));
  $('th').innerHTML='<tr>'+e.h.map(x=>`<th>${x}</th>`).join('')+'</tr>';
  $('tb').innerHTML='';$('sql').innerHTML='';
  const rows=()=>e.r.map((r,k)=>`<tr>`+r.map(c=>`<td>${c}</td>`).join('')+'</tr>');
  if(still){$('q').textContent=e.q;$('sql').innerHTML=e.sql.map(l=>`<span>${hl(l)}</span>`).join('');$('tb').innerHTML=rows().join('');return}
  $('q').innerHTML='<span class="caret"></span>';
  for(let c=1;c<=e.q.length;c++){$('q').innerHTML=esc(e.q.slice(0,c))+'<span class="caret"></span>';await sleep(26);if(t!==tok)return}
  await sleep(500);if(t!==tok)return;
  $('q').textContent=e.q;
  for(const l of e.sql){$('sql').insertAdjacentHTML('beforeend',`<span>${hl(l)}</span>`);await sleep(260);if(t!==tok)return}
  await sleep(300);
  for(const r of rows()){if(t!==tok)return;$('tb').insertAdjacentHTML('beforeend',r);await sleep(380)}
  await sleep(5000);if(t!==tok)return;
  run((cur+1)%EX.length);
}
run(0);
