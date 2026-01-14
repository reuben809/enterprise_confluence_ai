"""
POC Test Runner
Runs test questions through the system and generates evaluation report
"""

import json
import requests
import time
from datetime import datetime
from typing import List, Dict


API_URL = "http://localhost:8000"


def load_test_questions(filepath: str = "tests/poc_test_questions.json") -> Dict:
    """Load test questions from JSON file."""
    with open(filepath, 'r') as f:
        return json.load(f)


def run_single_test(question: Dict) -> Dict:
    """Run a single test question through the API."""
    print(f"\n{'='*80}")
    print(f"Test #{question['id']}: {question['question']}")
    print(f"Category: {question['category']}")
    print(f"{'='*80}")
    
    start_time = time.time()
    
    try:
        # Call the API
        response = requests.post(
            f"{API_URL}/chat",
            json={"question": question["question"], "history": []},
            stream=True,
            timeout=60
        )
        
        if not response.ok:
            return {
                "question_id": question["id"],
                "question": question["question"],
                "success": False,
                "error": f"API returned {response.status_code}",
                "latency": time.time() - start_time
            }
        
        # Parse streaming response
        answer = ""
        sources = []
        
        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line.decode('utf-8'))
                    if data["type"] == "token":
                        answer += data["data"]
                    elif data["type"] == "sources":
                        sources = data["data"]
                except json.JSONDecodeError:
                    continue
        
        latency = time.time() - start_time
        
        # Display results
        print(f"\n📝 ANSWER ({latency:.2f}s):")
        print(answer[:500] + "..." if len(answer) > 500 else answer)
        
        print(f"\n📚 SOURCES ({len(sources)}):")
        for i, src in enumerate(sources, 1):
            print(f"  {i}. {src['title']}")
        
        # Manual evaluation prompt
        print(f"\n🎯 EXPECTED SOURCES:")
        for src in question.get("expected_sources", []):
            print(f"  - {src}")
        
        print(f"\n✅ SUCCESS CRITERIA:")
        print(f"  {question.get('success_criteria', 'N/A')}")
        
        return {
            "question_id": question["id"],
            "question": question["question"],
            "category": question["category"],
            "answer": answer,
            "sources": sources,
            "latency": latency,
            "success": True,
            "expected_sources": question.get("expected_sources", []),
            "success_criteria": question.get("success_criteria", "")
        }
        
    except Exception as e:
        return {
            "question_id": question["id"],
            "question": question["question"],
            "success": False,
            "error": str(e),
            "latency": time.time() - start_time
        }


def generate_report(results: List[Dict], output_file: str = "tests/poc_results.json"):
    """Generate evaluation report."""
    
    # Calculate statistics
    total_tests = len(results)
    successful_tests = sum(1 for r in results if r.get("success", False))
    failed_tests = total_tests - successful_tests
    avg_latency = sum(r.get("latency", 0) for r in results) / total_tests if total_tests > 0 else 0
    
    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "summary": {
            "total_tests": total_tests,
            "successful": successful_tests,
            "failed": failed_tests,
            "success_rate": f"{(successful_tests/total_tests*100):.1f}%",
            "avg_latency": f"{avg_latency:.2f}s"
        },
        "results": results
    }
    
    # Save to file
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Print summary
    print(f"\n\n{'='*80}")
    print("📊 POC TEST SUMMARY")
    print(f"{'='*80}")
    print(f"Total Tests: {total_tests}")
    print(f"✅ Successful: {successful_tests}")
    print(f"❌ Failed: {failed_tests}")
    print(f"Success Rate: {report['summary']['success_rate']}")
    print(f"Avg Latency: {report['summary']['avg_latency']}")
    print(f"\n📄 Full report saved to: {output_file}")
    print(f"{'='*80}\n")
    
    return report


def main():
    """Run all POC tests."""
    print("🚀 Starting POC Test Suite")
    print(f"API URL: {API_URL}")
    
    # Check API health
    try:
        health = requests.get(f"{API_URL}/health", timeout=5)
        if not health.ok:
            print("❌ API is not healthy. Please start the server first.")
            return
        print("✅ API is healthy\n")
    except Exception as e:
        print(f"❌ Cannot connect to API: {e}")
        print("Please start the server with: uvicorn chat.chat_api:app --port 8000")
        return
    
    # Load test questions
    test_data = load_test_questions()
    questions = test_data["test_questions"]
    
    print(f"📋 Running {len(questions)} test questions...\n")
    
    # Run tests
    results = []
    for question in questions:
        result = run_single_test(question)
        results.append(result)
        
        # Pause between tests
        time.sleep(1)
    
    # Generate report
    generate_report(results)
    
    print("\n✨ POC testing complete!")
    print("\n💡 Next steps:")
    print("  1. Review the results in tests/poc_results.json")
    print("  2. Manually evaluate answer quality using the rubric")
    print("  3. Identify patterns in failed/poor answers")
    print("  4. Iterate on retrieval/prompts as needed")


if __name__ == "__main__":
    main()
