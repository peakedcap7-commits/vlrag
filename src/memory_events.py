"""记忆确认、撤销及查询；所有副作用在用户级事务锁内提交。"""

import base64
import json
import re
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import HTTPException


def _cursor(value):
    if not value:
        return ('1970-01-01T00:00:00+00:00', UUID(int=0))
    try:
        stamp, identifier = json.loads(base64.urlsafe_b64decode(value.encode()))
        parsed = datetime.fromisoformat(stamp)
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed, UUID(identifier)
    except Exception:
        raise HTTPException(422, 'invalid_cursor') from None


def _page(rows, identifier, previous, key='items'):
    cursor = previous
    if rows:
        cursor = base64.urlsafe_b64encode(json.dumps([
            rows[-1]['created_at'].isoformat(), str(rows[-1][identifier])
        ]).encode()).decode()
    return {'cursor': cursor, key: rows}


def lock_owner(cursor, identity):
    cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                   (f'{identity.tenant_id}:{identity.user_id}',))


def audit(cursor, identity, action, memory_id, actor='user'):
    cursor.execute(
        "INSERT INTO memory.audit_events(tenant_id,event_id,actor_user_id,actor_type,action,resource_type,resource_id,details,expires_at) "
        "VALUES(%s,%s,%s,%s,%s,'semantic',%s,'{}',now()+interval '365 days')",
        (identity.tenant_id, uuid4(), identity.user_id, actor, action, str(memory_id)))


def cap_memories(cursor, identity):
    for status, limit in (('active', 100), ('pending', 20)):
        cursor.execute(
            "UPDATE memory.semantic_memories SET status='deleted',embedding=NULL,deleted_at=now(),updated_at=now() "
            "WHERE tenant_id=%s AND memory_id IN (SELECT memory_id FROM memory.semantic_memories "
            "WHERE tenant_id=%s AND user_id=%s AND status=%s "
            "ORDER BY confidence DESC,updated_at DESC,memory_id DESC OFFSET %s) RETURNING memory_id",
            (identity.tenant_id, identity.tenant_id, identity.user_id, status, limit))
        ids = [row['memory_id'] for row in cursor.fetchall()]
        if ids:
            cursor.execute("UPDATE memory.memory_events SET status='expired',decided_at=now() "
                           "WHERE tenant_id=%s AND user_id=%s AND semantic_memory_id=ANY(%s) "
                           "AND status IN ('open','confirmed')", (identity.tenant_id, identity.user_id, ids))


class MemoryEventsMixin:
    def list_memory_events(self, identity, after=None, limit=20):
        stamp, identifier = _cursor(after)
        with self.transaction(identity) as cursor:
            cursor.execute(
                "SELECT event_id,kind,status,summary,(kind='semantic_confirmation_required' AND status='open') "
                "AS requires_confirmation,reversible_until,created_at FROM memory.memory_events "
                "WHERE tenant_id=%s AND user_id=%s AND expires_at>now() "
                "AND (created_at,event_id)>(%s,%s) ORDER BY created_at,event_id LIMIT %s",
                (identity.tenant_id, identity.user_id, stamp, identifier, min(max(limit,1),100)))
            return _page(list(cursor.fetchall()), 'event_id', after, 'events')

    def _event_snapshot(self, identity, event_id, cursor):
        cursor.execute('SELECT *,clock_timestamp() AS db_now FROM memory.memory_events '
                       'WHERE tenant_id=%s AND user_id=%s AND event_id=%s',
                       (identity.tenant_id, identity.user_id, event_id))
        event = cursor.fetchone()
        if not event:
            raise HTTPException(404, 'memory_event_not_found')
        if not event['semantic_memory_id']:
            return event, None, None
        cursor.execute('SELECT * FROM memory.semantic_memories WHERE tenant_id=%s AND user_id=%s AND memory_id=%s',
                       (identity.tenant_id, identity.user_id, event['semantic_memory_id']))
        current = cursor.fetchone()
        previous = None
        if current and current['supersedes_memory_id']:
            cursor.execute('SELECT * FROM memory.semantic_memories WHERE tenant_id=%s AND user_id=%s AND memory_id=%s',
                           (identity.tenant_id, identity.user_id, current['supersedes_memory_id']))
            previous = cursor.fetchone()
        return event, current, previous

    @staticmethod
    def _decision_check(event, current, previous, action):
        target = {'confirm':'confirmed', 'reject':'rejected', 'undo':'undone'}[action]
        if event['status'] == target:
            return True
        now = event['db_now']
        if event['status'] not in ('open', 'confirmed') or event['expires_at'] <= now:
            raise HTTPException(409, 'memory_event_expired_or_decided')
        if action == 'undo':
            if not event['reversible_until'] or event['reversible_until'] <= now:
                raise HTTPException(409, 'undo_expired')
        elif event['kind'] != 'semantic_confirmation_required' or event['status'] != 'open':
            raise HTTPException(409, 'incompatible_decision')
        if event['kind'] == 'episodic_saved':
            return False
        if not current or current['revision'] != event['expected_memory_revision']:
            raise HTTPException(409, 'memory_changed')
        expected_status = 'active' if action == 'undo' else 'pending'
        if current['status'] != expected_status:
            raise HTTPException(409, 'memory_changed')
        if current['expires_at'] and current['expires_at'] <= now:
            raise HTTPException(409, 'memory_expired')
        if action != 'reject' and event['expected_previous_revision'] is not None:
            if not previous or previous['revision'] != event['expected_previous_revision']:
                raise HTTPException(409, 'previous_memory_changed')
            if previous['status'] != ('superseded' if action == 'undo' else 'active'):
                raise HTTPException(409, 'previous_memory_changed')
            if previous['expires_at'] and previous['expires_at'] <= now:
                raise HTTPException(409, 'previous_memory_expired')
        return False

    def decide_memory_event(self, identity, event_id, action):
        from src.memory import _vector
        if action not in ('confirm','reject','undo'):
            raise HTTPException(422, 'invalid_decision')
        if not self.write_enabled:
            raise HTTPException(503, 'memory_write_disabled')
        # 向量服务不占用数据库锁；提交前重新读取版本及数据库时钟。
        with self.transaction(identity) as cursor:
            snapshot = self._event_snapshot(identity, event_id, cursor)
            if self._decision_check(*snapshot, action):
                return {'event_id': event_id, 'status': snapshot[0]['status'], 'reversible_until': snapshot[0]['reversible_until']}
        event, current, previous = snapshot
        restore = current if action == 'confirm' else previous if action == 'undo' else None
        vector = None
        if restore:
            vector = _vector(self.embeddings.embed_query(f"{restore['dimension']} {restore['value']} {restore['context'] or ''}"))
        with self.transaction(identity) as cursor:
            lock_owner(cursor, identity)
            fresh = self._event_snapshot(identity, event_id, cursor)
            if self._decision_check(*fresh, action):
                return {'event_id': event_id, 'status': fresh[0]['status'], 'reversible_until': fresh[0]['reversible_until']}
            if [(r['revision'] if r else None) for r in fresh[1:]] != [(r['revision'] if r else None) for r in snapshot[1:]]:
                raise HTTPException(409, 'memory_changed')
            event, current, previous = fresh
            target = {'confirm':'confirmed','reject':'rejected','undo':'undone'}[action]
            if event['kind'] == 'episodic_saved':
                cursor.execute("UPDATE memory.episodic_memories SET status='deleted',embedding=NULL,deleted_at=now(),updated_at=now() "
                               "WHERE tenant_id=%s AND owner_user_id=%s AND memory_id=%s AND scope='user' AND status='active' AND expires_at>now()",
                               (identity.tenant_id, identity.user_id, event['episodic_memory_id']))
                if cursor.rowcount != 1:
                    raise HTTPException(409, 'memory_changed')
            elif action == 'confirm':
                if previous:
                    cursor.execute("UPDATE memory.semantic_memories SET status='superseded',embedding=NULL,deleted_at=now(),updated_at=now() "
                                   "WHERE tenant_id=%s AND user_id=%s AND memory_id=%s RETURNING revision",
                                   (identity.tenant_id, identity.user_id, previous['memory_id']))
                    previous['revision'] = cursor.fetchone()['revision']
                cursor.execute("UPDATE memory.semantic_memories SET status='active',embedding=%s::vector,expires_at=NULL,updated_at=now() "
                               "WHERE tenant_id=%s AND user_id=%s AND memory_id=%s RETURNING revision",
                               (vector, identity.tenant_id, identity.user_id, current['memory_id']))
                revision = cursor.fetchone()['revision']
                cursor.execute("UPDATE memory.memory_events SET expected_memory_revision=%s,expected_previous_revision=%s,"
                               "reversible_until=now()+interval '7 days',expires_at=now()+interval '7 days' "
                               "WHERE tenant_id=%s AND event_id=%s", (revision, previous['revision'] if previous else None, identity.tenant_id,event_id))
            else:
                cursor.execute("UPDATE memory.semantic_memories SET status='deleted',embedding=NULL,deleted_at=now(),updated_at=now() "
                               "WHERE tenant_id=%s AND user_id=%s AND memory_id=%s", (identity.tenant_id,identity.user_id,current['memory_id']))
                if action == 'undo' and previous:
                    cursor.execute("UPDATE memory.semantic_memories SET status='active',embedding=%s::vector,deleted_at=NULL,updated_at=now() "
                                   "WHERE tenant_id=%s AND user_id=%s AND memory_id=%s", (vector,identity.tenant_id,identity.user_id,previous['memory_id']))
            cursor.execute('UPDATE memory.memory_events SET status=%s,decided_at=now() WHERE tenant_id=%s AND event_id=%s RETURNING reversible_until',
                           (target,identity.tenant_id,event_id))
            reversible_until = cursor.fetchone()['reversible_until']
            audit(cursor,identity,'memory.'+action,event_id)
            cap_memories(cursor,identity)
            return {'event_id':event_id,'status':target,'reversible_until':reversible_until}

    def forget_from_message(self, identity, message):
        # ponytail：只接受明确的遗忘请求和可定位的偏好；指代消解留给后续对话。
        if not re.search(r'(忘掉|忘记|删除).*(偏好|记忆|喜欢|喜好)|(?:请)?(?:忘掉|忘记)(?:这个|这条|这些)', message):
            return None
        rows = self.list_memories(identity, 'semantic')
        matches = [row for row in rows if row['value'] in message]
        if not matches:
            return '请具体说明要忘掉哪项偏好，例如“忘掉我喜欢黑色的偏好”。'
        for row in matches:
            self.delete_memory(identity,row['memory_id'])
        return '已忘掉你指定的偏好，不会恢复历史版本。'

    def list_admin_episodes(self, identity, status='pending', cursor=None, limit=20):
        self._require_admin(identity)
        if status not in ('pending','active','deleted'):
            raise HTTPException(422,'invalid_status')
        stamp, identifier = _cursor(cursor)
        with self.transaction(identity) as db:
            db.execute("SELECT memory_id,status,observation,action,result,created_at FROM memory.episodic_memories "
                       "WHERE tenant_id=%s AND scope='tenant' AND status=%s AND expires_at>now() "
                       "AND (created_at,memory_id)>(%s,%s) ORDER BY created_at,memory_id LIMIT %s",
                       (identity.tenant_id,status,stamp,identifier,min(max(limit,1),100)))
            return _page(list(db.fetchall()),'memory_id',cursor)

    def list_admin_runs(self, identity, feedback='positive', cursor=None, limit=20):
        self._require_admin(identity)
        if feedback != 'positive':
            raise HTTPException(422,'invalid_feedback')
        stamp, identifier = _cursor(cursor)
        with self.transaction(identity) as db:
            db.execute("SELECT r.run_id,r.intent,r.status,r.request_summary AS input_summary,r.response_summary AS output_summary,r.created_at "
                       "FROM memory.assistant_runs r WHERE r.tenant_id=%s AND r.expires_at>now() "
                       "AND EXISTS(SELECT FROM memory.assistant_feedback f WHERE f.tenant_id=r.tenant_id AND f.run_id=r.run_id "
                       "AND (f.event IN ('accepted','saved','purchased','thumbs_up') OR (f.event='rating' AND f.rating>=4))) "
                       "AND (r.created_at,r.run_id)>(%s,%s) ORDER BY r.created_at,r.run_id LIMIT %s",
                       (identity.tenant_id,stamp,identifier,min(max(limit,1),100)))
            return _page(list(db.fetchall()),'run_id',cursor)
