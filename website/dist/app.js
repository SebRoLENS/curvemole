const NS='http://www.w3.org/2000/svg';
function path(svg,d,color,fill='none',width=2){const el=document.createElementNS(NS,'path');el.setAttribute('d',d);el.setAttribute('stroke',color);el.setAttribute('fill',fill);el.setAttribute('stroke-width',width);svg.append(el)}
function curve(width,baseline,amp,centers,sizes){let d='';for(let x=0;x<=width;x+=2){let y=baseline;centers.forEach((c,i)=>y-=amp[i]*Math.exp(-.5*((x-c)/sizes[i])**2));d+=(x?'L':'M')+x.toFixed(1)+','+y.toFixed(2)}return d}
const views={overlay:['OVERLAY VIEW','Compare datasets<br>on shared axes.','Compare peak positions, line shapes and signal amplitudes across selected curves. Control the display of complete series or individual datasets.','CurveMole overlay view comparing three fitted spectra'],waterfall:['WATERFALL VIEW','Inspect trends<br>across a series.','Separate curves vertically to reveal patterns across a series. Follow peak shifts and shape changes without losing the context of the complete experiment.','CurveMole waterfall view with vertically offset spectra'],fit:['INTERACTIVE FITTING','Inspect components<br>and fit residuals.','Inspect the fitted model alongside individual components and residuals. Review parameter values and uncertainties before exporting results.','CurveMole multi-peak fit with components and residuals']};
const tabs=[...document.querySelectorAll('[data-view]')];function select(t){tabs.forEach(b=>{b.setAttribute('aria-selected',String(b===t));b.tabIndex=b===t?0:-1});const key=t.dataset.view,v=views[key];document.getElementById('viewLabel').textContent=v[0];document.getElementById('viewTitle').innerHTML=v[1];document.getElementById('viewText').textContent=v[2];setScreenshot(document.getElementById('viewImage'),key);document.getElementById('viewImage').alt=v[3];document.getElementById('view-panel').setAttribute('aria-labelledby',t.id)}tabs.forEach((t,i)=>{t.addEventListener('click',()=>select(t));t.addEventListener('keydown',e=>{let n;if(e.key==='ArrowRight')n=(i+1)%3;if(e.key==='ArrowLeft')n=(i+2)%3;if(e.key==='Home')n=0;if(e.key==='End')n=2;if(n!==undefined){e.preventDefault();tabs[n].focus();select(tabs[n])}})});

// These curves are actual fits computed with CurveMole, not a simulated optimizer.
// Animation progressively reveals the fitted curve and cycles through real results.
const hero=document.getElementById('heroPlot');
const motionPreference=matchMedia('(prefers-reduced-motion: reduce)');
const motionButton=document.getElementById('motionToggle');
let motionPaused=motionPreference.matches, heroVisible=true, frame=0, elapsed=0, lastTime=0, lastDraw=0, activeExample=-1, fitLine=null;
function svgText(x,y,text,extra={}){const el=document.createElementNS(NS,'text');el.setAttribute('x',x);el.setAttribute('y',y);el.setAttribute('fill','#a8bfcd');el.setAttribute('font-size','11');el.setAttribute('font-family','Arial, sans-serif');Object.entries(extra).forEach(([k,v])=>el.setAttribute(k,v));el.textContent=text;hero.append(el)}
function renderHero(index){
  const e=scientificExamples[index];hero.replaceChildren();
  const xmin=e.x[0],xmax=e.x[e.x.length-1];
  const low=Math.min(...e.y.map((y,i)=>y-e.sigma[i]),...e.fit),high=Math.max(...e.y.map((y,i)=>y+e.sigma[i]),...e.fit);
  const ymin=low-(high-low)*.08,ymax=high+(high-low)*.13;
  const X=x=>70+(x-xmin)/(xmax-xmin)*970,Y=y=>180-(y-ymin)/(ymax-ymin)*165;
  for(let i=0;i<5;i++){
    const y=ymin+(ymax-ymin)*i/4,py=Y(y);path(hero,`M70,${py}H1040`,'#263c49','none',.65);svgText(58,py+4,y.toFixed(1),{'text-anchor':'end'});
    const x=xmin+(xmax-xmin)*i/4,px=X(x);svgText(px,199,Math.abs(x)<100?x.toFixed(0):String(Math.round(x)),{'text-anchor':'middle'});
  }
  path(hero,'M70,15V180H1040','#506371','none',.8);
  svgText(555,224,e.xlabel,{'text-anchor':'middle','font-size':12});
  svgText(15,100,e.ylabel,{'text-anchor':'middle',transform:'rotate(-90 15 100)','font-size':12});
  e.x.forEach((x,i)=>{const px=X(x),py=Y(e.y[i]),top=Y(e.y[i]+e.sigma[i]),bottom=Y(e.y[i]-e.sigma[i]);path(hero,`M${px},${top}V${bottom}M${px-2},${top}H${px+2}M${px-2},${bottom}H${px+2}`,'#91aaba','none',.8);const dot=document.createElementNS(NS,'circle');dot.setAttribute('cx',px);dot.setAttribute('cy',py);dot.setAttribute('r','2');dot.setAttribute('fill','#dbe6ec');hero.append(dot)});
  const d=e.xx.map((x,i)=>(i?'L':'M')+X(x).toFixed(2)+','+Y(e.fit[i]).toFixed(2)).join('');
  path(hero,d,'#9bf3cd','none',2.2);fitLine=hero.lastChild;fitLine.setAttribute('pathLength','1');
  svgText(1035,11,`Data ±1σ · CurveMole weighted fit · χ²ᵣ = ${e.chi.toFixed(2)}`,{'text-anchor':'end','font-size':10,fill:'#9bf3cd'});
  document.getElementById('fitPhase').textContent=e.title;
  hero.setAttribute('aria-label',`${e.title}: synthetic data with one-sigma error bars and actual CurveMole fit. ${e.xlabel}; ${e.ylabel}.`);
}
function paintHero(){const index=Math.floor(elapsed/12000)%scientificExamples.length;if(index!==activeExample){activeExample=index;renderHero(index)}const reveal=motionPaused?1:Math.min(1,.25+(elapsed%12000)/4000+Math.min(scrollY/innerHeight,.7));fitLine.setAttribute('stroke-dasharray','1');fitLine.setAttribute('stroke-dashoffset',String(1-reveal))}
function tick(time){frame=0;if(motionPaused||!heroVisible||document.hidden){lastTime=0;return}if(lastTime)elapsed+=Math.min(time-lastTime,80);lastTime=time;if(time-lastDraw>32){paintHero();lastDraw=time}frame=requestAnimationFrame(tick)}
function resumeMotion(){if(!frame&&!motionPaused&&heroVisible&&!document.hidden)frame=requestAnimationFrame(tick)}
function applyMotion(){document.body.classList.toggle('motion-paused',motionPaused);motionButton.setAttribute('aria-pressed',String(motionPaused));motionButton.textContent=motionPaused?'Play animation ▷':'Pause animation Ⅱ';if(frame)cancelAnimationFrame(frame);frame=0;lastTime=0;paintHero();resumeMotion()}
motionButton.addEventListener('click',()=>{motionPaused=!motionPaused;applyMotion()});
motionPreference.addEventListener('change',e=>{motionPaused=e.matches;applyMotion()});
new IntersectionObserver(entries=>{heroVisible=entries[0].isIntersecting;resumeMotion()},{threshold:0}).observe(hero);
document.addEventListener('visibilitychange',resumeMotion);applyMotion();
// Reveal only when motion is allowed; all content remains readable without JS.
const revealObserver=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('revealed');revealObserver.unobserve(entry.target)}}),{threshold:.08});
document.querySelectorAll('.section-top,.steps article,.open-grid article,.fit-modes article,.downloads a').forEach((el,i)=>{el.classList.add('reveal');el.style.setProperty('--delay',`${i%4*70}ms`);revealObserver.observe(el)});
// Suspend decorative traces when the opening section is out of view.
const heroSection=document.querySelector('.hero');
new IntersectionObserver(entries=>heroSection.classList.toggle('hero-inactive',!entries[0].isIntersecting)).observe(heroSection);
document.addEventListener('visibilitychange',()=>document.body.classList.toggle('page-hidden',document.hidden));
