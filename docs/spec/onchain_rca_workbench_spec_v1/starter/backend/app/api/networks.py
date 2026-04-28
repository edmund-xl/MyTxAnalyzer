from fastapi import APIRouter

router = APIRouter()

@router.get("")
def list_networks():
    # TODO: read networks from database
    return []
