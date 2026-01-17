# app/eval/evaluator.py
class Evaluator:
    """
    A simple baseline evaluator for RAG systems.
    Returns 1 if the prediction exactly matches the reference, else 0.
    """

    def evaluate(self, prediction: str, reference: str) -> dict:
        """
        Evaluate prediction vs reference.
        
        Args:
            prediction (str): The generated answer.
            reference (str): The ground-truth or expected answer.
        
        Returns:
            dict: Evaluation result with score and match info.
        """
        score = int(prediction.strip().lower() == reference.strip().lower())
        return {
            "score": score,
            "match": bool(score),
            "prediction": prediction,
            "reference": reference
        }
