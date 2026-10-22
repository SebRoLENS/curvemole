const views={overlay:['OVERLAY VIEW','Compare datasets<br>on shared axes.','Compare peak positions, line shapes and signal amplitudes across selected curves. Control the display of complete series or individual datasets.','CurveMole overlay view comparing three fitted spectra'],waterfall:['WATERFALL VIEW','Inspect trends<br>across a series.','Separate curves vertically to reveal patterns across a series. Follow peak shifts and shape changes without losing the context of the complete experiment.','CurveMole waterfall view with vertically offset spectra'],fit:['INTERACTIVE FITTING','Inspect components<br>and fit residuals.','Inspect the fitted model alongside individual components and residuals. Review parameter values and uncertainties before exporting results.','CurveMole multi-peak fit with components and residuals']};
const tabs=[...document.querySelectorAll('[data-view]')];function select(t){tabs.forEach(b=>{b.setAttribute('aria-selected',String(b===t));b.tabIndex=b===t?0:-1});const key=t.dataset.view,v=views[key];document.getElementById('viewLabel').textContent=v[0];document.getElementById('viewTitle').innerHTML=v[1];document.getElementById('viewText').textContent=v[2];setScreenshot(document.getElementById('viewImage'),key);document.getElementById('viewImage').alt=v[3];document.getElementById('view-panel').setAttribute('aria-labelledby',t.id)}tabs.forEach((t,i)=>{t.addEventListener('click',()=>select(t));t.addEventListener('keydown',e=>{let n;if(e.key==='ArrowRight')n=(i+1)%3;if(e.key==='ArrowLeft')n=(i+2)%3;if(e.key==='Home')n=0;if(e.key==='End')n=2;if(n!==undefined){e.preventDefault();tabs[n].focus();select(tabs[n])}})});

// Only the decorative signal field moves; scientific results stay fully visible.
const motionPreference=matchMedia('(prefers-reduced-motion: reduce)');
const motionButton=document.getElementById('motionToggle');
let motionPaused=motionPreference.matches;
function applyMotion(){document.body.classList.toggle('motion-paused',motionPaused);motionButton.setAttribute('aria-pressed',String(motionPaused));motionButton.textContent=motionPaused?'Play background ▷':'Pause background Ⅱ'}
motionButton.addEventListener('click',()=>{motionPaused=!motionPaused;applyMotion()});
motionPreference.addEventListener('change',e=>{motionPaused=e.matches;applyMotion()});applyMotion();
// Reveal only when motion is allowed; all content remains readable without JS.
const revealObserver=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('revealed');revealObserver.unobserve(entry.target)}}),{threshold:.08});
document.querySelectorAll('.section-top,.steps article,.open-grid article,.fit-modes article,.downloads a').forEach((el,i)=>{el.classList.add('reveal');el.style.setProperty('--delay',`${i%4*70}ms`);revealObserver.observe(el)});
// Suspend decorative traces when the opening section is out of view.
const heroSection=document.querySelector('.hero');
new IntersectionObserver(entries=>heroSection.classList.toggle('hero-inactive',!entries[0].isIntersecting)).observe(heroSection);
document.addEventListener('visibilitychange',()=>document.body.classList.toggle('page-hidden',document.hidden));
