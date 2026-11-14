/* Government page: rotate through illustrative citizen and officer questions. */
"use strict";
(function(){
  const examples=[
    {
      who:"A citizen asks",
      lang:"hi",
      question:"मैं निर्माण श्रमिक हूँ। मैं किन योजनाओं के लिए आवेदन कर सकता हूँ?",
      answer:"आपके पंजीकरण के आधार पर तीन योजनाएँ उपयुक्त हो सकती हैं। आवेदन के लिए आधार, श्रमिक पंजीकरण कार्ड और बैंक पासबुक की आवश्यकता होगी।",
      source:"Scheme guidelines · Section 4 · Page 12"
    },
    {
      who:"An officer asks",
      lang:"en",
      question:"What is the latest circular on subsidy eligibility?",
      answer:"The most recent circular widens eligibility to include tenant farmers and replaces the earlier circular on the same subject.",
      source:"Circular No. 14 · Page 2"
    },
    {
      who:"A district officer asks",
      lang:"en",
      question:"Show pending grievances older than 15 days by district.",
      answer:"Lucknow: 42 · Kanpur Nagar: 37 · Prayagraj: 29",
      source:"Grievance database · Updated today"
    }
  ];
  const chips=document.getElementById("gov-chips");
  const who=document.getElementById("gov-who");
  const question=document.getElementById("gov-question");
  const answer=document.getElementById("gov-answer");
  if(!chips||!who||!question||!answer)return;

  let current=0;
  let timer;
  function show(index){
    current=index;
    const item=examples[index];
    chips.querySelectorAll("button").forEach((button,i)=>button.setAttribute("aria-pressed",String(i===index)));
    who.textContent=item.who;
    question.lang=item.lang;
    question.textContent=item.question;
    answer.innerHTML="";
    const text=document.createElement("p");
    text.lang=item.lang;
    text.textContent=item.answer;
    const source=document.createElement("span");
    source.className="gov-source";
    source.textContent=item.source;
    answer.append(text,source);
    clearTimeout(timer);
    timer=setTimeout(()=>show((current+1)%examples.length),6500);
  }
  chips.addEventListener("click",event=>{
    const button=event.target.closest("button");
    if(button)show(Number(button.dataset.i));
  });
  show(0);
})();
