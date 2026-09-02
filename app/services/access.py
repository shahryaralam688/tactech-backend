from app.core.exceptions import ForbiddenError, NotFoundError
from app.db import models
from app.repositories.trainee import TraineeRepository


def require_owned_trainee(trainees: TraineeRepository, trainer_id: str, trainee_id: str) -> models.TraineeProfile:
    trainee = trainees.get(trainee_id)
    if trainee is None:
        raise NotFoundError("Trainee not found.")
    if trainee.trainer_id != trainer_id:
        raise ForbiddenError("This trainee is not on your roster.")
    return trainee


def require_self_trainee(current_trainee_id: str, trainee_id: str) -> None:
    if current_trainee_id != trainee_id:
        raise ForbiddenError("You can only access your own data.")
