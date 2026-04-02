from abc import ABC, abstractmethod


class DealSource(ABC):
    name: str

    @abstractmethod
    def fetch(self):
        raise NotImplementedError
