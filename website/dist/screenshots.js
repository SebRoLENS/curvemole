// Real GUI captures of the original Raman example, regenerated with the app.
// Every workspace tab uses a dark-mode image; light mode is only in the comparison.
const screenshotFiles={fit:'fit-dark.png',overlay:'overlay-dark.png',waterfall:'waterfall-dark.png'};
function setScreenshot(img,key){if(screenshotFiles[key]){img.dataset.screenshot=key;img.src='assets/demo/'+screenshotFiles[key]}}
