import uuid
from pydantic import BaseModel, ConfigDict, ValidationError
from typing import Any, Awaitable, Callable, Coroutine, Dict, Generic, List, Optional, OrderedDict, Set, Tuple, TypeVar
from dataclasses import dataclass

import pygtrie



T = TypeVar("T")
@dataclass
class SingleVisitQueue(Generic[T]):
  """
  This data structure represents a queue of objects in which an object should only ever be added to the queue once, and all further adds will be rejected
  """
  queue: Set[T]
  has_ever_been_enqueued: Set[T]
  name: str

  @classmethod
  def construct(cls, name: str):
    return cls(
      queue=set(),
      has_ever_been_enqueued=set(),
      name=name
    )

  def add_to_queue(self, value: T, verbose: bool = False) -> bool:
    if value in self.has_ever_been_enqueued:
      # this url is either in the set already or has been visited
      was_added = False
    else:
      if verbose:
        print(f"Enqueuing: {value} to {self.name}")
      self.has_ever_been_enqueued.add(value)
      self.queue.add(value)
      was_added = True
    return was_added


  def pop_from_queue(self, prioritization_fn: Optional[Callable[[T], float]] = None) -> T:
    if prioritization_fn is None:
      result = self.queue.pop()
    else:
      result = min(self.queue, key=prioritization_fn)
      self.queue.remove(result)
    assert result not in self.queue
    assert result in self.has_ever_been_enqueued
    return result
  
  def is_empty(self) -> bool:
    return len(self.queue) == 0


@dataclass
class PrefixOptimizedSingleVisitQueue(SingleVisitQueue[str]):
  # NOTE: This needs to have a default because of the way that dataclass works
  trie: pygtrie.StringTrie

  @classmethod
  def construct(cls, name: str):
    return cls(
      queue=set(),
      has_ever_been_enqueued=set(),
      name=name,
      trie=pygtrie.StringTrie()
    )

  def prioritization_fn(self, string: str) -> int:
    longest_prefix = self.trie.longest_prefix(string)[0]
    return 0 if longest_prefix is None else len(longest_prefix)

  def pop_from_queue(self) -> T:
    # We pop the string that shares the shortest prefix with any string that has already been popped
    value = super().pop_from_queue(prioritization_fn=self.prioritization_fn)
    for i in range(len(value)):
      self.trie[value[:i]] = value
    return value



def _get_string_ordering_indices(string_list: List[str]) -> List[int]:
  # Given a list of urls, use the PrefixOptimizedSingleVisitQueue to determine the order in which they should be visited. Return a list of the indices of the urls in the order that they should be visited
  string_to_indices = {}
  for index, url in enumerate(string_list):
    string_to_indices[url] = index

  indices_list = []
  prefix_optimized_single_visit_queue = PrefixOptimizedSingleVisitQueue.construct(name="string_ordering")
  for url in string_to_indices.keys():
    prefix_optimized_single_visit_queue.add_to_queue(value=url)

  while not prefix_optimized_single_visit_queue.is_empty():
    url = prefix_optimized_single_visit_queue.pop_from_queue()
    indices_list.append(string_to_indices[url])
  
  if sorted(indices_list) != list(range(len(string_list))):
    raise RuntimeError(f"Indices list is not a permutation of the range of the length of the string list!\nstring_list: {string_list}\nsorted(indices_list): {sorted(indices_list)}\nlist(range(len(string_list))): {list(range(len(string_list)))}")
  return indices_list

T = TypeVar("T")
def sort_by_string(item_list: Set[T], fn: Optional[Callable[[T], str]] = None) -> List[T]:
  # sort the items in item_set based on the _get_string_ordering_indices of the result of fn
  if fn is None:
    # We add a random string after each one to guarantee that no two strings are equal. We need to add in the / because the trie uses this as a separator
    fn = lambda x: str(x) + "/" + str(uuid.uuid4())
  ordering_indices = _get_string_ordering_indices(string_list=[fn(item) for item in item_list])
  return [item_list[index] for index in ordering_indices]