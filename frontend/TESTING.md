# Frontend Testing Guide

This project uses **Jest** and **React Testing Library** for unit and integration testing.

## 1. Setup

To run the tests, you need to install the testing dependencies. Run the following command in the `frontend` directory:

```bash
npm install --save-dev jest jest-environment-jsdom @testing-library/react @testing-library/jest-dom @types/jest ts-jest
```

## 2. Configuration

Create a `jest.config.js` file in the `frontend` directory if it doesn't exist:

```javascript
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/$1',
  },
  transform: {
    '^.+\\.(ts|tsx)$': ['ts-jest', {
      tsconfig: 'tsconfig.json',
    }],
  },
};
```

Create a `jest.setup.js` file:

```javascript
import '@testing-library/jest-dom';
```

## 3. Running Tests

Run all tests:

```bash
npx jest
```

Run a specific test file:

```bash
npx jest hooks/useWebSocket
```

## 4. Test Coverage

The following components have initial test coverage:

- **`hooks/useWebSocket`**: Verifies connection, reconnection, and message validation.
- **`contexts/AccountContext`**: Verifies initial data fetching and order execution API calls.

## 5. Future Work

- Add tests for `MarketDataContext` and `SystemStatusContext`.
- Add integration tests for `BotControlModal` and `ManualTradePanel`.
