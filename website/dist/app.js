const views={overlay:['OVERLAY VIEW','Compare datasets<br>on shared axes.','Compare curve shapes, positions and amplitudes across selected datasets. Control the display of complete series or individual datasets.','Original CurveMole Raman overlay example in dark mode'],waterfall:['WATERFALL VIEW','Inspect trends<br>across a series.','Separate curves vertically to reveal patterns across a series. Inspect changes in position, width and amplitude across the selected curves.','Original CurveMole Raman waterfall example in dark mode'],fit:['INTERACTIVE FITTING','Inspect components<br>and fit residuals.','Inspect the fitted model alongside individual components and residuals. Review parameter values and uncertainties before exporting results.','Original CurveMole Raman fit and residuals in dark mode']};
const tabs=[...document.querySelectorAll('[data-view]')];function select(t){tabs.forEach(b=>{b.setAttribute('aria-selected',String(b===t));b.tabIndex=b===t?0:-1});const key=t.dataset.view,v=views[key];document.getElementById('viewLabel').textContent=v[0];document.getElementById('viewTitle').innerHTML=v[1];document.getElementById('viewText').textContent=v[2];setScreenshot(document.getElementById('viewImage'),key);document.getElementById('viewImage').alt=v[3];document.getElementById('view-panel').setAttribute('aria-labelledby',t.id)}tabs.forEach((t,i)=>{t.addEventListener('click',()=>select(t));t.addEventListener('keydown',e=>{let n;if(e.key==='ArrowRight')n=(i+1)%3;if(e.key==='ArrowLeft')n=(i+2)%3;if(e.key==='Home')n=0;if(e.key==='End')n=2;if(n!==undefined){e.preventDefault();tabs[n].focus();select(tabs[n])}})});

// Only the decorative signal field moves; scientific results stay fully visible.
const motionPreference=matchMedia('(prefers-reduced-motion: reduce)');
const motionButton=document.getElementById('motionToggle');
let motionPaused=motionPreference.matches;
function applyMotion(){document.body.classList.toggle('motion-paused',motionPaused);motionButton.setAttribute('aria-pressed',String(motionPaused));motionButton.textContent=motionPaused?'Play background ▷':'Pause background Ⅱ'}
motionButton.addEventListener('click',()=>{motionPaused=!motionPaused;applyMotion()});
motionPreference.addEventListener('change',e=>{motionPaused=e.matches;applyMotion()});applyMotion();
// Both screenshots show the same original Raman example and viewport.
const themeSlider=document.getElementById('themeSlider');
const comparison=document.querySelector('.theme-comparison'),comparisonImages=document.querySelector('.theme-images');
function updateThemeSplit(value){const split=Math.max(0,Math.min(100,Math.round(value)));themeSlider.value=String(split);comparison.style.setProperty('--split',split+'%');themeSlider.setAttribute('aria-valuetext',split+'% dark')}
themeSlider.addEventListener('input',()=>updateThemeSplit(Number(themeSlider.value)));
let comparisonPointer=null;
function moveComparison(event){const bounds=comparisonImages.getBoundingClientRect();updateThemeSplit((event.clientX-bounds.left)/bounds.width*100)}
comparisonImages.querySelectorAll('img').forEach(img=>img.draggable=false);
comparisonImages.addEventListener('pointerdown',event=>{if(!event.isPrimary||event.button!==0)return;comparisonPointer=event.pointerId;comparisonImages.setPointerCapture(event.pointerId);moveComparison(event)});
comparisonImages.addEventListener('pointermove',event=>{if(event.pointerId===comparisonPointer)moveComparison(event)});
for(const eventName of ['pointerup','pointercancel'])comparisonImages.addEventListener(eventName,()=>{comparisonPointer=null});
// Suspend decorative traces when the opening section is out of view.
const heroSection=document.querySelector('.hero');
new IntersectionObserver(entries=>heroSection.classList.toggle('hero-inactive',!entries[0].isIntersecting)).observe(heroSection);
document.addEventListener('visibilitychange',()=>document.body.classList.toggle('page-hidden',document.hidden));
