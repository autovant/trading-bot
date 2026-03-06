import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/layout/Layout';
import { Dashboard } from './pages/Dashboard';
import { Config } from './pages/Config';
import { Backtesting } from './pages/Backtesting';

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/config" element={<Config />} />
          <Route path="/backtesting" element={<Backtesting />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
