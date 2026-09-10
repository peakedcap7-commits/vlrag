"""真实 PostgreSQL 集成验证；只对显式指定的 *_test 数据库创建合成数据。"""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from fastapi import HTTPException

from src.auth import Identity
from src.memory import MemoryService
from src.memory_events import _cursor, cap_memories, lock_owner
from src.memory_migrate import LOGIN_ROLE_ENV, migrate
from src.memory_worker import MemoryWorker, PreferenceMemory


class CursorTest(unittest.TestCase):
    def test_invalid_cursor_is_not_accepted(self):
        for cursor in ('bad', 'W10=', 'WyIyMDI2LTAxLTAxIiwiYmFkIl0='):
            with self.assertRaises(HTTPException):
                _cursor(cursor)


@unittest.skipUnless(os.getenv('MEMORY_EVENTS_TEST_DSN'), '需要独立 *_test PostgreSQL')
class MemoryEventsIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.connect = staticmethod(psycopg.connect)
        cls.dsn = os.environ['MEMORY_EVENTS_TEST_DSN']
        if not urlsplit(cls.dsn).path.endswith('_test'):
            raise RuntimeError('只运行合成测试数据库')
        passwords = {role:'synthetic-memory-test-only' for role in LOGIN_ROLE_ENV}
        migrate(cls.dsn,passwords)
        migrate(cls.dsn)
        parts = urlsplit(cls.dsn)
        def url(role):
            return urlunsplit(parts._replace(netloc=f'{role}:synthetic-memory-test-only@{parts.hostname}:{parts.port or 5432}'))
        cls.embed = Mock()
        cls.embed.embed_query.return_value = [1.0]+[0.0]*1023
        cls.embed.embed_documents.side_effect = lambda rows:[[1.0]+[0.0]*1023 for _ in rows]
        cls.api = MemoryService(url('shopping_memory_api_login'),embeddings=cls.embed)
        cls.worker_memory = MemoryService(url('shopping_memory_worker_login'),embeddings=cls.embed)
        cls.poller = url('shopping_memory_poller_login')
        cls.maintenance = url('shopping_memory_maintenance_login')

    @classmethod
    def tearDownClass(cls):
        cls.api.close()
        cls.worker_memory.close()

    def setUp(self):
        self.identity = Identity(uuid4(),uuid4(),frozenset())
        self.worker = MemoryWorker.__new__(MemoryWorker)
        self.worker.memory = self.worker_memory
        self.worker.poller_url = self.poller
        self.worker.worker_id = uuid4()
        self.worker._connect = self.connect
        self.worker.semantic_manager = Mock()
        self.embed.embed_query.side_effect = None

    def save(self, value='黑色', polarity=1, pending=False, existing_id=None):
        message = f'我一直{"喜欢" if polarity>0 else "不喜欢"}{value}'
        run_id = self.api.record_run(self.identity,uuid4(),{'message':message},
                                     {'intent':'outfit_analyze','status':'ok','conversation_state':{'last_intent':'outfit_analyze'}})
        # 独立领取本测试任务，避免其他测试遗留队列改变次序。
        with self.connect(self.dsn) as db:
            from psycopg.rows import dict_row
            with db.cursor(row_factory=dict_row) as cursor:
                cursor.execute("UPDATE memory.memory_jobs SET status='running',locked_by=%s,locked_at=now(),attempts=1 "
                               "WHERE tenant_id=%s AND source_run_id=%s RETURNING *",(self.worker.worker_id,self.identity.tenant_id,run_id))
                job=cursor.fetchone()
        item=PreferenceMemory(dimension='color',value=value,polarity=polarity,confidence=.9,
                              durability='inferred' if pending else 'explicit',evidence=message)
        self.worker.semantic_manager.invoke.return_value=[SimpleNamespace(id=str(existing_id or uuid4()),content=item)]
        self.worker._semantic(self.identity,job)
        with self.api.transaction(self.identity) as cursor:
            cursor.execute('SELECT e.* FROM memory.memory_events e JOIN memory.semantic_memories s '
                           'ON s.tenant_id=e.tenant_id AND s.memory_id=e.semantic_memory_id WHERE s.source_run_id=%s',(run_id,))
            event=cursor.fetchone()
        return event,job

    def rows(self):
        return self.api.list_memories(self.identity,'semantic')

    def test_reverse_undo_and_idempotency(self):
        first,_=self.save()
        second,job=self.save(polarity=-1,existing_id=first['semantic_memory_id'])
        self.assertEqual(self.rows()[0]['polarity'],-1)
        existing=self.worker.semantic_manager.invoke.call_args.args[0]['existing']
        self.assertEqual(existing[0][0],str(first['semantic_memory_id']))
        self.worker._semantic(self.identity,job)
        self.assertEqual(len(self.api.list_memory_events(self.identity)['events']),2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.api.decide_memory_event(self.identity,second['event_id'],'undo'),range(2)))
        self.assertEqual([r['status'] for r in results],['undone','undone'])
        self.assertEqual(self.rows()[0]['polarity'],1)

    def test_pending_confirmation_then_undo(self):
        first,_=self.save()
        second,_=self.save(polarity=-1,pending=True,existing_id=first['semantic_memory_id'])
        self.assertEqual(self.rows()[0]['polarity'],1)
        self.api.decide_memory_event(self.identity,second['event_id'],'confirm')
        self.assertEqual(self.rows()[0]['polarity'],-1)
        self.api.decide_memory_event(self.identity,second['event_id'],'undo')
        self.assertEqual(self.rows()[0]['polarity'],1)

    def test_followup_and_restored_revision_block_old_undo(self):
        a,_=self.save()
        b,_=self.save(polarity=-1,existing_id=a['semantic_memory_id'])
        c,_=self.save(polarity=1,existing_id=b['semantic_memory_id'])
        with self.assertRaises(HTTPException):
            self.api.decide_memory_event(self.identity,b['event_id'],'undo')
        self.api.decide_memory_event(self.identity,c['event_id'],'undo')
        self.assertEqual(self.rows()[0]['polarity'],-1)
        with self.assertRaises(HTTPException):
            self.api.decide_memory_event(self.identity,b['event_id'],'undo')

    def test_embedding_failure_and_expiration_leave_data_intact(self):
        a,_=self.save()
        b,_=self.save(polarity=-1,existing_id=a['semantic_memory_id'])
        self.embed.embed_query.side_effect=RuntimeError('synthetic embedding failure')
        with self.assertRaises(RuntimeError):
            self.api.decide_memory_event(self.identity,b['event_id'],'undo')
        self.assertEqual(self.rows()[0]['polarity'],-1)
        self.embed.embed_query.side_effect=None
        with self.connect(self.dsn) as db:
            db.execute("UPDATE memory.memory_events SET reversible_until=now() WHERE tenant_id=%s AND event_id=%s",(self.identity.tenant_id,b['event_id']))
        with self.assertRaises(HTTPException) as caught:
            self.api.decide_memory_event(self.identity,b['event_id'],'undo')
        self.assertEqual(caught.exception.detail,'undo_expired')

    def test_reject_forget_and_cross_user_isolation(self):
        a,_=self.save()
        b,_=self.save(polarity=-1,pending=True,existing_id=a['semantic_memory_id'])
        other=Identity(self.identity.tenant_id,uuid4(),frozenset())
        self.assertEqual(self.api.list_memory_events(other)['events'],[])
        with self.assertRaises(HTTPException) as caught:
            self.api.decide_memory_event(other,b['event_id'],'confirm')
        self.assertEqual(caught.exception.status_code,404)
        self.api.decide_memory_event(self.identity,b['event_id'],'reject')
        self.assertEqual(self.rows()[0]['polarity'],1)
        self.assertIn('已忘掉',self.api.forget_from_message(self.identity,'忘掉我喜欢黑色的偏好'))
        self.assertEqual(self.rows(),[])
        with self.assertRaises(HTTPException):
            self.api.decide_memory_event(self.identity,a['event_id'],'undo')

    def test_maintenance_entry_is_only_grant_and_reclaims(self):
        event,_=self.save(pending=True)
        with self.connect(self.dsn) as db:
            db.execute("UPDATE memory.semantic_memories SET expires_at=created_at WHERE tenant_id=%s AND memory_id=%s",
                       (self.identity.tenant_id,event['semantic_memory_id']))
        with self.connect(self.maintenance) as db:
            db.execute('SELECT memory.run_memory_maintenance()')
        with self.connect(self.maintenance) as db:
            with self.assertRaises(Exception):
                db.execute('SELECT memory.purge_expired_rows()')
        with self.api.transaction(self.identity) as cursor:
            cursor.execute('SELECT status FROM memory.semantic_memories WHERE memory_id=%s',(event['semantic_memory_id'],))
            self.assertEqual(cursor.fetchone()['status'],'deleted')

    def test_graph_state_is_persisted_and_admin_lists_other_user_runs(self):
        thread=uuid4()
        run=self.api.record_run(self.identity,thread,{'conversation_state':{'old':True}},
                               {'intent':'outfit_analyze','status':'ok','conversation_state':{'selected_item_ids':['demo']}})
        self.assertEqual(self.api.load_thread(self.identity,thread),{'selected_item_ids':['demo']})
        self.api.add_feedback(self.identity,SimpleNamespace(event='saved',rating=None,comment=None,idempotency_key='one',run_id=run,thread_id=thread))
        admin=Identity(self.identity.tenant_id,uuid4(),frozenset({'tenant_admin'}))
        self.assertEqual(self.api.list_admin_runs(admin)['items'][0]['run_id'],run)

    def test_capacity_and_retention_preserve_live_undo(self):
        a,_=self.save()
        b,_=self.save(polarity=-1,existing_id=a['semantic_memory_id'])
        with self.connect(self.dsn) as db:
            revision=db.execute("UPDATE memory.semantic_memories SET deleted_at=now()-interval '8 days' "
                                "WHERE tenant_id=%s AND memory_id=%s RETURNING revision",
                                (self.identity.tenant_id,a['semantic_memory_id'])).fetchone()[0]
            db.execute('UPDATE memory.memory_events SET expected_previous_revision=%s WHERE tenant_id=%s AND event_id=%s',
                       (revision,self.identity.tenant_id,b['event_id']))
        with self.connect(self.maintenance) as db:
            db.execute('SELECT memory.run_memory_maintenance()')
        self.api.decide_memory_event(self.identity,b['event_id'],'undo')
        self.assertEqual(self.rows()[0]['polarity'],1)
        with self.connect(self.dsn) as db:
            for i in range(102):
                db.execute("INSERT INTO memory.semantic_memories(tenant_id,memory_id,user_id,dimension,value,polarity,confidence,embedding,status) "
                           "VALUES(%s,%s,%s,'style',%s,1,.1,%s::vector,'active')",
                           (self.identity.tenant_id,uuid4(),self.identity.user_id,f'test{i}','['+','.join(['1']+['0']*1023)+']'))
            for i in range(22):
                db.execute("INSERT INTO memory.semantic_memories(tenant_id,memory_id,user_id,dimension,value,polarity,confidence,status,expires_at) "
                           "VALUES(%s,%s,%s,'style',%s,1,.1,'pending',now()+interval '7 days')",
                           (self.identity.tenant_id,uuid4(),self.identity.user_id,f'pending{i}'))
        with self.api.transaction(self.identity) as cursor:
            lock_owner(cursor,self.identity)
            cap_memories(cursor,self.identity)
            cursor.execute("SELECT status,count(*) AS n FROM memory.semantic_memories WHERE tenant_id=%s AND user_id=%s GROUP BY status",
                           (self.identity.tenant_id,self.identity.user_id))
            counts={r['status']:r['n'] for r in cursor.fetchall()}
        self.assertEqual(counts['active'],100)
        self.assertEqual(counts['pending'],20)

    def test_reject_and_cross_tenant_and_confirmation_race(self):
        event,_=self.save(pending=True)
        other=Identity(uuid4(),self.identity.user_id,frozenset())
        with self.assertRaises(HTTPException) as caught:
            self.api.decide_memory_event(other,event['event_id'],'confirm')
        self.assertEqual(caught.exception.status_code,404)
        # 向量计算期间发生遗忘，重验必须失败且不能重新激活。
        def embed(_):
            self.api.delete_memory(self.identity,event['semantic_memory_id'])
            return [1.0]+[0.0]*1023
        self.embed.embed_query.side_effect=embed
        with self.assertRaises(HTTPException):
            self.api.decide_memory_event(self.identity,event['event_id'],'confirm')
        self.embed.embed_query.side_effect=None
        self.assertEqual(self.rows(),[])


if __name__=='__main__':
    unittest.main()
