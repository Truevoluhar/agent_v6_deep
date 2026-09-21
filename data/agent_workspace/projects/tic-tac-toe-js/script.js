const cells = Array.from(document.querySelectorAll('.cell'));
const statusText = document.getElementById('status');
const newRoundButton = document.getElementById('newRoundButton');
const resetButton = document.getElementById('resetButton');
const xScoreText = document.getElementById('xScore');
const oScoreText = document.getElementById('oScore');
const drawScoreText = document.getElementById('drawScore');

const winningLines = [
  [0, 1, 2],
  [3, 4, 5],
  [6, 7, 8],
  [0, 3, 6],
  [1, 4, 7],
  [2, 5, 8],
  [0, 4, 8],
  [2, 4, 6],
];

let board = Array(9).fill('');
let currentPlayer = 'X';
let gameActive = true;
let scores = {
  X: 0,
  O: 0,
  draws: 0,
};

function handleCellClick(event) {
  const cell = event.target;
  const index = Number(cell.dataset.index);

  if (!gameActive || board[index] !== '') {
    return;
  }

  placeMark(index);
  const winningLine = getWinningLine();

  if (winningLine) {
    endGameWithWinner(winningLine);
    return;
  }

  if (board.every(Boolean)) {
    endGameWithDraw();
    return;
  }

  switchPlayer();
}

function placeMark(index) {
  board[index] = currentPlayer;
  cells[index].textContent = currentPlayer;
  cells[index].classList.add(currentPlayer.toLowerCase());
  cells[index].disabled = true;
}

function getWinningLine() {
  return winningLines.find((line) => {
    const [a, b, c] = line;
    return board[a] && board[a] === board[b] && board[a] === board[c];
  });
}

function endGameWithWinner(winningLine) {
  gameActive = false;
  scores[currentPlayer] += 1;
  updateScoreboard();
  statusText.textContent = `Player ${currentPlayer} wins!`;

  winningLine.forEach((index) => cells[index].classList.add('win'));
  cells.forEach((cell) => (cell.disabled = true));
}

function endGameWithDraw() {
  gameActive = false;
  scores.draws += 1;
  updateScoreboard();
  statusText.textContent = "It's a draw!";
}

function switchPlayer() {
  currentPlayer = currentPlayer === 'X' ? 'O' : 'X';
  statusText.textContent = `Player ${currentPlayer}'s turn`;
}

function startNewRound() {
  board = Array(9).fill('');
  currentPlayer = 'X';
  gameActive = true;
  statusText.textContent = "Player X's turn";

  cells.forEach((cell) => {
    cell.textContent = '';
    cell.disabled = false;
    cell.className = 'cell';
  });
}

function resetScore() {
  scores = {
    X: 0,
    O: 0,
    draws: 0,
  };
  updateScoreboard();
  startNewRound();
}

function updateScoreboard() {
  xScoreText.textContent = scores.X;
  oScoreText.textContent = scores.O;
  drawScoreText.textContent = scores.draws;
}

cells.forEach((cell) => cell.addEventListener('click', handleCellClick));
newRoundButton.addEventListener('click', startNewRound);
resetButton.addEventListener('click', resetScore);
