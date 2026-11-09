"""Build a focused read-only diagnostic from the exact failed mobile verifier.

This is not release acceptance. The original 30-second condition and the
public/authenticated read isolation remain unchanged. Only closed DOM states
are reported; owner text, prices, IDs, URLs and credentials are not emitted.
"""
from pathlib import Path
import subprocess

BASE = '6e9b181e0c07fde6b4e0e55083c9b1967ce5188e'
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip() == BASE
p=Path('web/scripts/mobile-today-acceptance.mjs');source=p.read_text()
marker="      }, { expectedSymbol: symbol, expectedHorizon: horizon }, { timeout: 30_000 });"
assert source.count(marker)==1
addition=r'''      }, { expectedSymbol: symbol, expectedHorizon: horizon }, { timeout: 30_000 }).catch(async error => {
        const state = await page.evaluate(({symbol,horizon}) => {
          const a=document.querySelector('[data-argus-contract="other-market-actuals-explorer-v1"]');
          const c=document.querySelector('[data-argus-contract="canonical-market-snapshot-v1"]');
          return {actualsPresent:!!a,otherSymbolMatches:a?.getAttribute('data-other-market-symbol')===symbol,
            otherHorizonMatches:a?.getAttribute('data-other-market-horizon')===horizon,
            selectedSnapshotPresent:!!a?.querySelector('[data-market-snapshot-id]')?.getAttribute('data-market-snapshot-id'),
            canonicalPresent:!!c,canonicalNikkei:c?.getAttribute('data-canonical-instrument')==='N225',
            canonicalFiveDay:c?.getAttribute('data-canonical-horizon')==='5D',
            canonicalVerified:c?.getAttribute('data-canonical-verification')==='verified',
            ownerLocked:!!document.querySelector('.owner-access-screen'),hidden:document.hidden};
        }, {symbol,horizon}).catch(()=>({pageReadFailed:true}));
        const closed={schemaVersion:'argus-mobile259-wait-diagnostic-v1',status:'WAIT_CONDITION_NOT_MET',
          symbol,horizon,conditionTimeoutMs:30000,state,completedCombinations:evidence.combinations.length,
          observedSnapshotResponses:evidence.snapshotBodies.size,notReadyResponses:evidence.notReady.length,
          rateLimitResponses:evidence.rateLimits.length,aiPostCount:evidence.aiPostCount,
          acceptanceClaimed:false,rawOwnerDataIncluded:false};
        await writeJson('closed-wait-state.json',closed);
        console.error('MOBILE259_CLOSED_STATE '+JSON.stringify(closed));
        throw error;
      });'''
source=source.replace(marker,addition)
stop='  await page.setViewportSize({ width: 430, height: 932 });\n  await page.locator(\'.nav__mobile\').getByRole(\'button\', { name: \'Today\', exact: true }).click();\n  for (const viewport of VIEWPORTS) {'
assert source.count(stop)==1
replacement='''  const closed={schemaVersion:'argus-mobile259-wait-diagnostic-v1',status:'TWELVE_CONDITIONS_NOW_MET',
    completedCombinations:evidence.combinations.length,conditionTimeoutMs:30000,
    failedContractChecks:evidence.failures.length,observedSnapshotResponses:evidence.snapshotBodies.size,
    notReadyResponses:evidence.notReady.length,rateLimitResponses:evidence.rateLimits.length,
    aiPostCount:evidence.aiPostCount,acceptanceClaimed:false,originalFailureCauseRepaired:false,
    rawOwnerDataIncluded:false};
  await writeJson('closed-wait-state.json',closed);
  console.log('MOBILE259_CLOSED_STATE '+JSON.stringify(closed));
  return;
''' + stop
source=source.replace(stop,replacement)
Path('web/scripts/mobile259-focused-read.generated.mjs').write_text(source)
