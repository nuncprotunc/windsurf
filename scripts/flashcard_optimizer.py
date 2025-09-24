import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from tqdm import tqdm

class FlashcardSimulator:
    def __init__(self, n_simulations=1_000_000, deck_size=150):
        self.n_simulations = n_simulations
        self.deck_size = deck_size
        self.results = []
        
    def simulate_retention(self, card_type, n_cards, days=30, reviews_per_day=3):
        """Simulate retention based on card type and study parameters"""
        if card_type == 'name_recognition':
            base_retention = 0.7
            decay_rate = 0.15
        elif card_type == 'active_recall':
            base_retention = 0.85
            decay_rate = 0.08
        else:  # applied
            base_retention = 0.6
            decay_rate = 0.12
            
        total_retention = 0
        for _ in range(n_cards):
            retention = base_retention * (1 - decay_rate) ** (days / reviews_per_day)
            total_retention += min(1.0, max(0, retention + np.random.normal(0, 0.05)))
        return total_retention / n_cards if n_cards > 0 else 0
    
    def run_simulation(self):
        for _ in tqdm(range(self.n_simulations), desc="Running simulations"):
            # Randomly generate deck composition
            name_recognition = np.random.randint(15, 36)  # 15-35 cards (10-23%)
            active_recall = np.random.randint(90, 106)    # 90-105 cards (60-70%)
            applied = self.deck_size - name_recognition - active_recall
            
            # Ensure we have a valid distribution
            if applied < 10 or applied > 30:  # 7-20% of deck
                continue
                
            # Simulate retention
            nr_retention = self.simulate_retention('name_recognition', name_recognition)
            ar_retention = self.simulate_retention('active_recall', active_recall)
            ap_retention = self.simulate_retention('applied', applied)
            
            # Calculate weighted score
            total_retention = (nr_retention * name_recognition + 
                             ar_retention * active_recall + 
                             ap_retention * applied) / self.deck_size
            
            # Store results
            self.results.append({
                'name_recognition': name_recognition,
                'active_recall': active_recall,
                'applied': applied,
                'total_retention': total_retention
            })
    
    def analyze_results(self, top_n=1000):
        if not self.results:
            self.run_simulation()
            
        df = pd.DataFrame(self.results)
        top_performers = df.nlargest(top_n, 'total_retention')
        
        # Calculate optimal distribution
        optimal = {
            'name_recognition': int(round(top_performers['name_recognition'].mean())),
            'active_recall': int(round(top_performers['active_recall'].mean())),
            'applied': int(round(top_performers['applied'].mean())),
            'avg_retention': top_performers['total_retention'].mean()
        }
        
        return optimal, df
    
    def plot_results(self, df):
        plt.figure(figsize=(14, 7))
        
        # Scatter plot
        plt.subplot(1, 2, 1)
        scatter = plt.scatter(df['active_recall']/self.deck_size*100, 
                   df['total_retention']*100, 
                   c=df['applied']/self.deck_size*100, 
                   cmap='viridis',
                   alpha=0.6)
        plt.colorbar(scatter, label='% Applied Cards')
        plt.xlabel('% Active Recall Cards')
        plt.ylabel('Average Retention (%)')
        plt.title('Flashcard Optimization Space')
        plt.grid(True, alpha=0.3)
        
        # 3D Visualization
        plt.subplot(1, 2, 2, projection='3d')
        sc = plt.scatter(df['name_recognition'], 
                        df['active_recall'], 
                        df['applied'], 
                        c=df['total_retention']*100,
                        cmap='viridis')
        plt.colorbar(sc, label='Retention (%)')
        plt.xlabel('Name Rec')
        plt.ylabel('Active Recall')
        plt.gca().set_zlabel('Applied')
        plt.title('Optimal Flashcard Mix')
        
        plt.tight_layout()
        plt.savefig('flashcard_optimization.png', dpi=300, bbox_inches='tight')
        plt.close()

if __name__ == "__main__":
    print("=== Flashcard Optimization Simulation ===")
    print(f"Running {1_000_000:,} Monte Carlo iterations...\n")
    
    simulator = FlashcardSimulator(n_simulations=1_000_000)
    optimal, results_df = simulator.analyze_results()
    
    print("\n=== Optimal Flashcard Distribution ===")
    print(f"Name Recognition: {optimal['name_recognition']:2d} cards ({optimal['name_recognition']/150*100:.1f}%)")
    print(f"Active Recall:    {optimal['active_recall']:2d} cards ({optimal['active_recall']/150*100:.1f}%)")
    print(f"Applied/Scenario: {optimal['applied']:2d} cards ({optimal['applied']/150*100:.1f}%)")
    print(f"\nPredicted Retention: {optimal['avg_retention']*100:.1f}%")
    
    # Generate visualization
    simulator.plot_results(results_df)
    print("\nVisualization saved as 'flashcard_optimization.png'")
