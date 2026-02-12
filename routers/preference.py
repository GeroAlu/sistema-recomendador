from fastapi import APIRouter, HTTPException
from schemas import PreferenceInput, Error
from database import get_db_connection

router = APIRouter(tags=["Preferencias"])

@router.post("/preference", responses={400: {"model": Error}, 404: {"model": Error}})
def add_preference(pref: PreferenceInput):
    dbConnection = get_db_connection()
    try:
        value = 10 if pref.interactionType == 'PURCHASE' else 1
        with dbConnection.cursor() as cur:
            cur.execute(
                "INSERT INTO preferences (user_id, item_id, interaction_type, value) VALUES (%s, %s, %s, %s)",
                (pref.userId, pref.itemId, pref.interactionType, value)
            )
            dbConnection.commit()
            return {"message": "Preferencia registrada exitosamente"}
    except Exception as e:
        dbConnection.rollback()
        msg = str(e)
        if "foreign key" in msg.lower():
             raise HTTPException(status_code=404, detail={"code": "INVALID_REF", "message": "Usuario o Item no existen."})
        raise HTTPException(status_code=400, detail={"code": "DB_ERROR", "message": msg})
    finally:
        dbConnection.close()
