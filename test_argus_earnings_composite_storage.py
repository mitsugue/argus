"""Composite receipt storage and the existing private snapshot/restore boundary."""
import base64
import copy
import json
import pytest
import argus_earnings_history as history
import argus_earnings_scope as scope
import argus_market_input_backup as backup
import jp_market_acquisition as sources
from test_argus_earnings_scope import fixture, bind, add_row
from test_argus_market_input_backup import Remote


def proof_rows():
    inputs=fixture();add_row(inputs);bind(inputs)
    return scope.admit(**inputs)


def resigned(proof):
    proof['compositeSha256']=scope.digest({k:v for k,v in proof.items() if k!='compositeSha256'})
    return proof


def test_original_observation_and_old_date_company_receipts_unchanged(tmp_path):
    proof,rows=proof_rows();path=tmp_path/'source.sqlite3';old_at='2018-05-12T16:00:00+00:00'
    old=history.retain(path,rows,received_at=old_at,member_codes=proof['memberCodes'],
                       query_date=proof['queryDate'],complete_scope=proof['memberCodes'],query_code='1000')
    db=sources.connect(path)
    originals={table:db.execute('SELECT * FROM '+table).fetchall() for table in ('raw_sources','observations','metadata')};db.close()
    result=history.retain_composite(path,rows,receipt_proof=proof)
    assert result['complete'] and result['newObservations']==0
    assert result['collectionKind']=='COMPANY_DATE_COMPONENT_SET'
    db=sources.connect(path)
    for table,entries in originals.items():
        actual=db.execute('SELECT * FROM '+table).fetchall()
        # Latest date cursor can move; all original immutable revisions stay.
        assert all(entry in actual for entry in entries if not (table=='metadata' and ':revision:' not in entry[0]))
    db.close()
    assert history.read_coverage(path,cutoff=old_at)[proof['queryDate']]==old
    assert history.read_coverage(path,cutoff=proof['knownAt'])[proof['queryDate']]==result
    assert history.read_company_coverage(path,cutoff=proof['knownAt'],member_codes=['1000'])['1000']['receivedAt']==old_at
    observed=history.read(path,cutoff=proof['knownAt'],member_codes=['1000'])[0]
    assert observed['receivedAt']==observed['knownAt']==old_at


def test_composite_alone_never_certifies_whole_company_or_historical_receipt(tmp_path):
    proof,rows=proof_rows();path=tmp_path/'source.sqlite3'
    history.retain_composite(path,rows,receipt_proof=proof)
    assert history.read_company_coverage(path,cutoff=proof['knownAt'],member_codes=proof['memberCodes'])=={}
    assert history.read_coverage(path,cutoff='2017-05-12T18:00:00+09:00')=={}


@pytest.mark.parametrize('mutate,category',[
    (lambda p:p['components'].pop(),'ALL_COMPONENTS_REQUIRED'),
    (lambda p:p['components'][0].update(selectedRowsSha256='a'*64),'COMPONENT_SELECTED_INPUT'),
    (lambda p:p.update(knownAt='2017-05-12T18:00:00+09:00'),'COMPOSITE_AVAILABILITY'),
    (lambda p:p['components'][0]['pages'][0].update(owner='forbidden'),'PAGE_FIELDS'),
    (lambda p:p['components'][0].update(owner='forbidden'),'COMPONENT_FIELDS'),
    (lambda p:p.update(wholeMarketDateQueryAccepted=True),'COMPOSITE_AUTHORITY'),
    (lambda p:p.update(companyFullHistoryReceiptAccepted=True),'COMPOSITE_AUTHORITY'),
    (lambda p:p.update(actionAuthority=True),'COMPOSITE_AUTHORITY'),
])
def test_invalid_composite_rejected_before_store_creation(tmp_path,mutate,category):
    proof,rows=proof_rows();mutate(proof);resigned(proof);path=tmp_path/'absent.sqlite3'
    with pytest.raises(ValueError,match=category):history.retain_composite(path,rows,receipt_proof=proof)
    assert not path.exists()


def corrupt_metadata(path,mutate):
    db=sources.connect(path)
    for key,raw in db.execute("SELECT key,value FROM metadata WHERE key LIKE 'financial-summary-date:%'").fetchall():
        row=json.loads(raw);mutate(row);row.pop('coverageSha256')
        row['coverageSha256']=scope.digest(row)
        db.execute('UPDATE metadata SET value=? WHERE key=?',(sources._json(row),key))
    db.commit();db.close()


def test_outer_resigning_cannot_hide_corrupt_nested_proof_in_read_or_backup(tmp_path):
    proof,rows=proof_rows();path=tmp_path/'source.sqlite3'
    history.retain_composite(path,rows,receipt_proof=proof)
    corrupt_metadata(path,lambda r:r['componentReceipt']['components'].pop())
    with pytest.raises(ValueError,match='COMPOSITE_HASH'):history.read_coverage(path,cutoff=proof['knownAt'])
    remote=Remote()
    with pytest.raises(ValueError,match='COMPOSITE_HASH'):backup.synchronize(path,remote)
    assert remote.writes==0


def test_resigned_nested_owner_field_rejected_before_private_export(tmp_path):
    proof,rows=proof_rows();path=tmp_path/'source.sqlite3';history.retain_composite(path,rows,receipt_proof=proof)
    def mutate(row):
        row['componentReceipt']['components'][0]['owner']='forbidden'
        resigned(row['componentReceipt'])
    corrupt_metadata(path,mutate);remote=Remote()
    with pytest.raises(ValueError,match='COMPONENT_FIELDS'):backup.synchronize(path,remote)
    assert remote.writes==0


def test_composite_uses_same_private_snapshot_restore_with_all_component_hashes(tmp_path):
    proof,rows=proof_rows();path=tmp_path/'source.sqlite3';history.retain_composite(path,rows,receipt_proof=proof)
    expected=history.read_coverage(path,cutoff=proof['knownAt']);remote=Remote()
    result=backup.synchronize(path,remote)
    assert result['status']=='VERIFIED' and result['counts']['financial']==1
    assert result['counts']['coverageReceipts']==2
    manifest=json.loads(remote.files[backup.PREFIX+'/manifests/'+result['manifestSha256']+'.json'])
    content=b''.join(remote.files[backup.PREFIX+'/chunks/'+c['sha256']+'.bin'] for c in manifest['chunks'])
    restored=tmp_path/'restored.sqlite3';db=sources.connect(restored)
    for entry in [json.loads(line) for line in content.splitlines()][1:]:
        if entry['kind']=='raw':
            db.execute('INSERT INTO raw_sources VALUES(?,?,?,?,?)',(entry['id'],entry['url'],entry['sha256'],entry['receivedAt'],base64.b64decode(entry['dataBase64'])))
        elif entry['kind']=='coverage':db.execute('INSERT INTO metadata VALUES(?,?)',(entry['key'],sources._json(entry['body'])))
        elif entry['kind']=='observation':
            db.execute('INSERT INTO observations(source_id,session,raw_id,body) VALUES(?,?,?,?)',
                       (entry['sourceId'],entry['session'],entry['rawId'],sources._json(entry['body'])))
    db.commit();db.close()
    assert history.read_coverage(restored,cutoff=proof['knownAt'])==expected
    assert history.read_company_coverage(restored,cutoff=proof['knownAt'],member_codes=proof['memberCodes'])=={}
    assert history.read(restored,cutoff=proof['knownAt'],member_codes=['1000'])==history.read(path,cutoff=proof['knownAt'],member_codes=['1000'])
    writes=remote.writes
    assert backup.synchronize(path,remote)==result and remote.writes==writes
