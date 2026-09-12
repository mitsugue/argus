"""Independent encrypted recovery worker; status reads never perform network IO."""
import threading
import time
import argus_owner_dialogue_backup as backup


class RecoveryWorker:
    def __init__(self, *, storage_path, configuration, keys, remote, now):
        self.storage_path=storage_path;self.configuration=configuration;self.keys=keys;self.remote=remote;self.now=now
        self._lock=threading.Lock();self._state_lock=threading.Lock();self._pending=False
        self._state={'status':'NOT_RUN','lastAttemptAt':None,'lastVerifiedAt':None,'lastAttemptMonotonic':None,
            'restoredThisBoot':False,'configurationId':None,'headVersion':None,'errorClass':None}

    def status(self):
        configured,identity=self.configuration()
        with self._state_lock:
            state={k:v for k,v in self._state.items() if k not in ('configurationId','headVersion','lastAttemptMonotonic','keyId')}
            ready=not configured or (self._state['restoredThisBoot'] and self._state['configurationId']==identity)
            pending=self._pending
        return {**state,'configured':configured,'generationReady':ready,'pending':pending,'remoteRecoveryVerified':False}

    def tick(self,force=False):
        with self._state_lock:
            if force:self._pending=True
            last=self._state['lastAttemptMonotonic']
            due=force or self._pending or last is None or time.monotonic()-last>=600
        if not due or not self._lock.acquire(blocking=False):return
        try:threading.Thread(target=self._run,daemon=True,name='owner-dialogue-recovery').start()
        except Exception:
            self._lock.release()
            with self._state_lock:self._state.update(status='FAILED',errorClass='WorkerStartFailed')

    def _run(self):
        try:
            for _ in range(2):
                configured,identity=self.configuration()
                with self._state_lock:
                    self._pending=False;previous=dict(self._state)
                    self._state.update(status='RUNNING',lastAttemptAt=self.now(),lastAttemptMonotonic=time.monotonic())
                path=self.storage_path()
                if not configured:
                    with self._state_lock:self._state.update(status='NOT_CONFIGURED')
                    return
                try:
                    if not path:raise ValueError('dialogue_recovery_durable_path_unavailable')
                    result=backup.synchronize(path,self.remote(),self.keys(),previous=previous if previous['configurationId']==identity else None)
                    with self._state_lock:
                        self._state.update(result,lastVerifiedAt=self.now(),restoredThisBoot=True,configurationId=identity,errorClass=None)
                except Exception as exc:
                    with self._state_lock:self._state.update(status='FAILED',errorClass=type(exc).__name__)
                    return
                with self._state_lock:again=self._pending
                if not again:return
        finally:self._lock.release()
