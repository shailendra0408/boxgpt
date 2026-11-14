/* Banking page: role-based dashboard switcher. */
"use strict";
const $=id=>document.getElementById(id);
const ROLES={
admin:{n:'Admin',who:'Head office administrator',scope:'Whole organisation, no customer-level data by default',ask:'How many questions did each team ask this month?',
 k:[['12,480','Questions this month'],['214','Active users'],['37','Queries blocked by policy'],['2.4 s','Average response time']],ct:'Questions by team',
 b:[['Branch operations',34],['Relationship managers',27],['Credit',18],['Compliance',12],['Others',9]],lt:'Recent activity',
 l:[['09:41','Access policy updated for the Credit team'],['09:12','Query blocked: customer PAN lookup by a branch clerk'],['08:50','New user added for Lucknow branch'],['08:15','Audit log exported by Compliance']],
 can:['Add users and assign roles','Set which tables and fields each role can query','View usage, blocked queries and the audit log'],no:['See customer balances or personal details','Run queries on behalf of other users']},
branch:{n:'Branch manager',who:'Hazratganj branch',scope:'Own branch only',ask:'Loans overdue by more than 30 days in my branch',
 k:[['4,120','Active clients'],['₹ 3.4 L','Average monthly balance'],['63','Loans overdue'],['118','New accounts, 30 days']],ct:'Deposits by week (₹ crore)',
 b:[['Week 1',12],['Week 2',15],['Week 3',14],['Week 4',19]],lt:'Recent questions',
 l:[['10:24','Clients with a balance above ₹5 lakh'],['09:50','Overdue EMIs by loan type'],['09:05','Accounts opened this week'],['08:40','Idle accounts older than 6 months']],
 can:['Query all clients and loans of the own branch','Export results for branch reviews'],no:['See other branches','See head-office or HR data']},
rm:{n:'Relationship manager',who:'Assigned portfolio',scope:'180 assigned clients',ask:'Which of my clients have idle balances above ₹2 lakh?',
 k:[['180','Assigned clients'],['14','Renewals due'],['22','Idle balances'],['9','Follow-ups today']],ct:'Clients by segment',
 b:[['Salaried',64],['Business owners',52],['Senior citizens',38],['NRI',26]],lt:'Recent questions',
 l:[['10:02','Fixed deposits maturing this month'],['09:30','Clients with falling balances'],['09:10','Loan eligibility above ₹10 lakh'],['08:45','Clients with no contact in 60 days']],
 can:['Query own assigned clients','See balances, products and follow-ups'],no:['See clients of other managers','See branch-wide or bank-wide totals']},
comp:{n:'Compliance officer',who:'Audit and risk',scope:'All branches, read-only',ask:'Accounts with KYC expiring in the next 30 days',
 k:[['21','Flagged transactions'],['86','KYC expiring soon'],['15','Reviewed today'],['9,310','Audit log entries']],ct:'Flags by branch',
 b:[['Hazratganj',7],['Gomti Nagar',5],['Aliganj',4],['Others',5]],lt:'Recent questions',
 l:[['10:15','Cash deposits just under the reporting limit'],['09:40','Dormant accounts with sudden activity'],['09:00','KYC pending by branch'],['08:30','Queries run by user, last 7 days']],
 can:['Query across all branches for review','Read the full audit log'],no:['Edit records or approve transactions','Change access policies']}};
$('rtabs').innerHTML=Object.keys(ROLES).map(k=>`<button data-k="${k}" aria-pressed="false">${ROLES[k].n}</button>`).join('');
function dash(k){const r=ROLES[k],mx=Math.max(...r.b.map(x=>x[1]));
 document.querySelectorAll('#rtabs button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.k===k));
 $('dash').innerHTML=`<div class="dwin"><div class="dhead"><div><b>${r.n} dashboard</b><span class="w">${r.who}</span></div><span class="scope"><svg class="i"><use href="/assets/icons.svg#lock"/></svg>Sees: ${r.scope}</span></div>
 <div class="askbar">${r.ask}<span>Ask</span></div>
 <div class="kpis">${r.k.map((x,i)=>`<div class="kpi"><strong>${x[0]}</strong><span>${x[1]}</span></div>`).join('')}</div>
 <div class="dgrid"><div class="pnl"><h4>${r.ct}</h4>${r.b.map(x=>`<div class="bar"><span>${x[0]}</span><i data-w="${Math.round(x[1]/mx*100)}"></i><em>${x[1]}</em></div>`).join('')}</div>
 <div class="pnl"><h4>${r.lt}</h4>${r.l.map(x=>`<div class="li"><span>${x[0]}</span><b>${x[1]}</b></div>`).join('')}</div></div></div>
 <div class="access"><div><h4>Can see and do</h4><ul>${r.can.map(x=>`<li>${x}</li>`).join('')}</ul></div><div><h4>Cannot see</h4><ul>${r.no.map(x=>`<li>${x}</li>`).join('')}</ul></div></div>`;
 requestAnimationFrame(()=>requestAnimationFrame(()=>document.querySelectorAll('#dash .bar i').forEach(e=>e.style.width=e.dataset.w+'%')));}
$('rtabs').onclick=e=>{const b=e.target.closest('button');if(b)dash(b.dataset.k)};dash('admin');
