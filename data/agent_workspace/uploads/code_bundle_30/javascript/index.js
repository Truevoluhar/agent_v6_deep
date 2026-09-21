function sum(values) {
  return values.reduce((total, value) => total + value, 0);
}

console.log(sum([1, 2, 3, 4]));
