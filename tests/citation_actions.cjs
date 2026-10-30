const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('each button copies only its own reference and reports clipboard failure', async () => {
  const elements = {
    citationText: {textContent: 'Version-specific citation.'},
    citationDoi: {href: 'https://doi.org/version'},
    citationMethods: {textContent: 'CurveMole version 1.1.0 (RRID:SCR_029214).'},
    citationConceptText: {textContent: 'General project citation.'},
    citationConceptDoi: {href: 'https://doi.org/concept'},
    citationStatus: {}, methodsStatus: {}, projectCitationStatus: {},
  };
  const buttons = ['version', 'methods', 'project'].map(key => ({
    dataset: {copy: key},
    addEventListener(event, callback) { this.click = callback; },
  }));
  let copied;
  let fail = false;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../website/dist/citation.js'), 'utf8'), {
    document: {getElementById: id => elements[id], querySelectorAll: () => buttons},
    navigator: {clipboard: {writeText: async text => {
      if (fail) throw Error('Clipboard unavailable');
      copied = text;
    }}},
  });
  await buttons[0].click();
  assert.equal(copied, 'Version-specific citation. https://doi.org/version');
  await buttons[1].click();
  assert.equal(copied, elements.citationMethods.textContent);
  await buttons[2].click();
  assert.equal(copied, 'General project citation. https://doi.org/concept');
  fail = true;
  await buttons[0].click();
  assert.match(elements.citationStatus.textContent, /Select the text/);
});
